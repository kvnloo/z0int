/**
 * z0int bridge — immutable OMP transport shim (v2).
 *
 * This file is intentionally dumb:
 *   OMP events → stable serialization → trace lifecycle → resident worker IPC
 *
 * Experimental logic lives in `python -u -m z0int.bridge.worker` and is
 * hot-swapped on `/reload-plugins` without restarting the OMP session.
 *
 * ONE restart is required after installing this shim. After that, bridge
 * Python edits take effect via /reload-plugins (transactional generation swap).
 *
 * execution remains log_only until host consume is authorized.
 */
import { randomUUID } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface, type Interface } from "node:readline";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const BRIDGE_PROTOCOL = "z0int.bridge.v2";
const Z0 = join(homedir(), ".z0int");
const RUNTIME = join(Z0, "runtime");
const CURRENT = join(RUNTIME, "bridge-current.json");

const Z0_PY =
	process.env.Z0INT_PYTHON ||
	"/home/kvn/tmp/openjev/.venv/bin/python";
const Z0_ROOT =
	process.env.Z0INT_ROOT ||
	// Prefer the tree that owns this extension when possible.
	process.env.Z0INT_BRIDGE_ROOT ||
	"/home/kvn/tmp/openjev";

const WORKER_TIMEOUT_MS = Number(process.env.Z0INT_BRIDGE_TIMEOUT_MS || 45_000);
const HANDSHAKE_TIMEOUT_MS = 20_000;

type Jsonish = Record<string, unknown>;

type WorkerHello = {
	ok: boolean;
	protocol?: string;
	generation?: number;
	instance_id?: string;
	build_id?: string;
	error?: string;
};

type Pending = {
	id: string;
	resolve: (value: Jsonish) => void;
	reject: (error: Error) => void;
	timer: ReturnType<typeof setTimeout>;
};

type ActiveTurn = {
	traceId: string;
	sessionId: string;
	openedGeneration: number;
};

type WorkerHandle = {
	child: ChildProcess;
	lines: Interface;
	generation: number;
	instanceId: string;
	buildId: string;
	pending: Map<string, Pending>;
};

let current: WorkerHandle | null = null;
let generation = 0;
let reloadPromise: Promise<Jsonish> | null = null;
let activeTurn: ActiveTurn | null = null;

function ensureDir(path: string): void {
	mkdirSync(path, { recursive: true });
}

function publishCurrent(h: WorkerHandle): void {
	ensureDir(RUNTIME);
	const blob = {
		protocol: BRIDGE_PROTOCOL,
		generation: h.generation,
		instance_id: h.instanceId,
		build_id: h.buildId,
		activated_at: Date.now() / 1000,
		omp_pid: process.pid,
	};
	writeFileSync(CURRENT, JSON.stringify(blob, null, 2) + "\n", "utf8");
}

function failAll(h: WorkerHandle, err: Error): void {
	for (const p of h.pending.values()) {
		clearTimeout(p.timer);
		p.reject(err);
	}
	h.pending.clear();
}

function spawnWorker(nextGen: number): Promise<WorkerHandle> {
	return new Promise((resolve, reject) => {
		const env = {
			...process.env,
			Z0INT_ROOT: Z0_ROOT,
			PYTHONPATH: join(Z0_ROOT, "src") + (process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""),
			Z0INT_BRIDGE_GENERATION: String(nextGen),
		};
		const child = spawn(Z0_PY, ["-u", "-m", "z0int.bridge.worker", "--generation", String(nextGen)], {
			cwd: Z0_ROOT,
			env,
			stdio: ["pipe", "pipe", "pipe"],
		});
		const pending = new Map<string, Pending>();
		const lines = createInterface({ input: child.stdout! });
		const handle: WorkerHandle = {
			child,
			lines,
			generation: nextGen,
			instanceId: "pending",
			buildId: "pending",
			pending,
		};

		lines.on("line", line => {
			let msg: Jsonish;
			try {
				msg = JSON.parse(line) as Jsonish;
			} catch (e) {
				return;
			}
			const id = typeof msg.id === "string" ? msg.id : "";
			const p = id ? pending.get(id) : undefined;
			if (!p) return;
			pending.delete(id);
			clearTimeout(p.timer);
			p.resolve(msg);
		});

		child.stderr?.on("data", () => {
			/* keep resident quiet unless debugging */
		});

		child.on("exit", code => {
			failAll(handle, new Error(`z0int bridge worker exited ${code}`));
			if (current === handle) current = null;
		});

		child.on("error", err => {
			failAll(handle, err instanceof Error ? err : new Error(String(err)));
			reject(err instanceof Error ? err : new Error(String(err)));
		});

		// handshake
		const helloId = randomUUID();
		const timer = setTimeout(() => {
			try {
				child.kill("SIGKILL");
			} catch {
				/* */
			}
			reject(new Error("bridge worker hello timeout"));
		}, HANDSHAKE_TIMEOUT_MS);

		pending.set(helloId, {
			id: helloId,
			timer,
			resolve: msg => {
				if (msg.ok !== true) {
					reject(new Error(String(msg.error || "hello_failed")));
					return;
				}
				if (msg.protocol !== BRIDGE_PROTOCOL) {
					try {
						child.kill("SIGKILL");
					} catch {
						/* */
					}
					reject(new Error(`protocol_mismatch:${msg.protocol}`));
					return;
				}
				handle.instanceId = String(msg.instance_id || "unknown");
				handle.buildId = String(msg.build_id || "unknown");
				if (typeof msg.generation === "number") handle.generation = msg.generation;
				resolve(handle);
			},
			reject: err => reject(err),
		});

		try {
			child.stdin!.write(
				JSON.stringify({ id: helloId, op: "hello", bridge_generation: nextGen }) + "\n",
			);
		} catch (e) {
			clearTimeout(timer);
			pending.delete(helloId);
			reject(e instanceof Error ? e : new Error(String(e)));
		}
	});
}

async function request(h: WorkerHandle, body: Jsonish, timeoutMs = WORKER_TIMEOUT_MS): Promise<Jsonish> {
	const id = randomUUID();
	const { promise, resolve, reject } = Promise.withResolvers<Jsonish>();
	const timer = setTimeout(() => {
		h.pending.delete(id);
		reject(new Error(`bridge worker timeout op=${body.op}`));
	}, timeoutMs);
	h.pending.set(id, { id, resolve, reject, timer });
	const line = JSON.stringify({ id, bridge_generation: h.generation, ...body }) + "\n";
	if (!h.child.stdin || h.child.killed) {
		h.pending.delete(id);
		clearTimeout(timer);
		return Promise.reject(new Error("bridge worker stdin closed"));
	}
	h.child.stdin.write(line);
	return promise;
}

async function selfCheck(h: WorkerHandle): Promise<Jsonish> {
	return request(h, { op: "self_check" }, HANDSHAKE_TIMEOUT_MS);
}

async function drainAndStop(h: WorkerHandle): Promise<void> {
	try {
		await request(h, { op: "drain" }, 3000);
	} catch {
		/* */
	}
	try {
		await request(h, { op: "shutdown" }, 3000);
	} catch {
		/* */
	}
	try {
		h.child.kill("SIGTERM");
	} catch {
		/* */
	}
	setTimeout(() => {
		try {
			if (h.child.exitCode === null) h.child.kill("SIGKILL");
		} catch {
			/* */
		}
	}, 2000);
}

async function ensureWorker(): Promise<WorkerHandle> {
	if (current && current.child.exitCode === null) return current;
	const nextGen = generation + 1 || 1;
	const h = await spawnWorker(nextGen);
	const check = await selfCheck(h);
	if (check.ok !== true) {
		await drainAndStop(h);
		throw new Error(`self_check failed: ${JSON.stringify(check.errors || check.error)}`);
	}
	current = h;
	generation = h.generation;
	publishCurrent(h);
	publishShadowTransport(h);
	maybePrewarmDecider(h);
	return h;
}

async function reload(reason: string): Promise<Jsonish> {
	if (reloadPromise) return reloadPromise;
	reloadPromise = (async () => {
		if (activeTurn) {
			return {
				ok: false,
				error: "turn_in_flight",
				deferred: true,
				generation,
				reason,
			};
		}
		const nextGen = generation + 1;
		let next: WorkerHandle;
		try {
			next = await spawnWorker(nextGen);
			const check = await selfCheck(next);
			if (check.ok !== true) {
				await drainAndStop(next);
				return {
					ok: false,
					error: "self_check_failed",
					detail: check,
					generation,
					reason,
				};
			}
		} catch (e) {
			return {
				ok: false,
				error: e instanceof Error ? e.message : String(e),
				generation,
				reason,
			};
		}
		const previous = current;
		current = next;
		generation = next.generation;
		publishCurrent(next);
		publishShadowTransport(next);
		maybePrewarmDecider(next);
		if (previous) void drainAndStop(previous);
		return {
			ok: true,
			generation: next.generation,
			build_id: next.buildId,
			instance_id: next.instanceId,
			reason,
		};
	})().finally(() => {
		reloadPromise = null;
	});
	return reloadPromise;
}

function resolveSessionId(ctx: unknown): string {
	if (ctx && typeof ctx === "object" && "sessionId" in ctx) {
		const s = (ctx as { sessionId?: unknown }).sessionId;
		if (typeof s === "string" && s) return s;
	}
	return process.env.OMP_SESSION_ID || `omp-${process.pid}`;
}

function estimateMeasuredFromMessages(messages: unknown[]): {
	input_tokens: number;
	output_tokens: number;
	measured: number;
	provider: string | null;
	model: string | null;
} {
	// Char/4 proxy until OMP exposes provider usage on the event.
	let chars = 0;
	let provider: string | null = null;
	let model: string | null = null;
	const walk = (node: unknown, depth = 0): void => {
		if (depth > 8 || node == null) return;
		if (typeof node === "string") {
			chars += node.length;
			return;
		}
		if (Array.isArray(node)) {
			for (const x of node) walk(x, depth + 1);
			return;
		}
		if (typeof node === "object") {
			const o = node as Record<string, unknown>;
			if (typeof o.provider === "string" && !provider) provider = o.provider;
			if (typeof o.model === "string" && !model) model = o.model;
			if (typeof o.text === "string") chars += o.text.length;
			if (typeof o.content === "string") chars += o.content.length;
			for (const v of Object.values(o)) walk(v, depth + 1);
		}
	};
	walk(messages);
	const measured = Math.max(1, Math.ceil(chars / 4));
	// split rough 40/60 in/out
	const input_tokens = Math.floor(measured * 0.4);
	const output_tokens = measured - input_tokens;
	return { input_tokens, output_tokens, measured, provider, model };
}


type ShadowTransport = {
	kind: "z0int-bridge";
	request: (body: Jsonish, timeoutMs?: number) => Promise<Jsonish>;
	warm: (backend: string) => Promise<Jsonish>;
	generation?: number;
	buildId?: string;
	instanceId?: string;
};

function publishShadowTransport(h: WorkerHandle | null): void {
	const g = globalThis as { __omp_z0int_bridge_transport__?: ShadowTransport };
	if (!h) {
		delete g.__omp_z0int_bridge_transport__;
		return;
	}
	g.__omp_z0int_bridge_transport__ = {
		kind: "z0int-bridge",
		generation: h.generation,
		buildId: h.buildId,
		instanceId: h.instanceId,
		request: (body, timeoutMs) => request(h, body, timeoutMs),
		warm: (backend) =>
			request(h, { op: "decision_warm", payload: { backend } }, 5_000),
	};
}

function maybePrewarmDecider(h: WorkerHandle): void {
	const env = String(process.env.OMP_SHADOW_WORKER_NEEDED || "").toLowerCase();
	const enabled = env === "1" || env === "true" || env === "on";
	if (!enabled) return;
	// Non-blocking — never await during OMP startup / handshake.
	void request(h, { op: "decision_warm", payload: { backend: "decider_2b" } }, 5_000).catch(() => {
		/* fail-open */
	});
}

export default function z0intBridge(pi: ExtensionAPI) {
	pi.setLabel("z0int bridge v2 (resident worker, log-only)");

	// Eager start so first turn is warm.
	void ensureWorker().catch(() => {
		/* fail-open; next turn retries */
	});

	// /reload-plugins interception: hot-swap worker, then let OMP continue.
	pi.on("input", async (event, ctx) => {
		const text =
			event && typeof event === "object" && "text" in event
				? String((event as { text?: unknown }).text ?? "").trim()
				: "";
		if (text !== "/reload-plugins") return;
		// Do NOT return { handled: true } — OMP must still run builtin reload.
		try {
			const result = await reload("omp_reload_plugins");
			const ok = result.ok === true;
			const gen = result.generation;
			const build = result.build_id;
			ctx.ui?.notify?.(
				ok
					? `z0int bridge → generation ${gen} build=${build}`
					: `z0int bridge reload failed (${result.error}); keeping generation ${generation}`,
				ok ? "info" : "warning",
			);
		} catch (e) {
			ctx.ui?.notify?.(`z0int bridge reload error: ${e}`, "warning");
		}
	});

	pi.on("before_agent_start", async (event, ctx) => {
		const prompt =
			event && typeof event === "object" && "prompt" in event
				? String((event as { prompt?: unknown }).prompt ?? "").trim()
				: "";
		const sessionId = resolveSessionId(ctx);
		if (!prompt || prompt.startsWith("/")) return;

		try {
			const h = await ensureWorker();
			const turn: ActiveTurn = {
				traceId: randomUUID().replaceAll("-", ""),
				sessionId,
				openedGeneration: h.generation,
			};
			activeTurn = turn;
			await request(h, {
				op: "turn_open",
				trace_id: turn.traceId,
				session_id: turn.sessionId,
				omp_pid: process.pid,
				payload: { prompt, session_id: turn.sessionId, omp_pid: process.pid },
			});
		} catch {
			activeTurn = null;
		}
	});

	async function closeActive(messages: unknown[], source: string): Promise<void> {
		const turn = activeTurn;
		if (!turn) return;
		const est = estimateMeasuredFromMessages(messages);
		try {
			const h = await ensureWorker();
			await request(h, {
				op: source === "bridge_agent_end" ? "agent_end" : "turn_close",
				trace_id: turn.traceId,
				session_id: turn.sessionId,
				omp_pid: process.pid,
				payload: {
					trace_id: turn.traceId,
					session_id: turn.sessionId,
					omp_pid: process.pid,
					measured: est.measured,
					input_tokens: est.input_tokens,
					output_tokens: est.output_tokens,
					execution_completed: true,
					// verified_success stays null until async join
					source,
					provider: est.provider,
					model: est.model,
					opened_generation: turn.openedGeneration,
					close_generation: h.generation,
				},
			});
		} catch {
			/* fail-open */
		} finally {
			if (activeTurn?.traceId === turn.traceId) activeTurn = null;
		}
	}

	pi.on("turn_end", async event => {
		try {
			const msg =
				event && typeof event === "object" && "message" in event
					? (event as { message?: unknown }).message
					: null;
			await closeActive(msg ? [msg] : [], "bridge_turn_end");
		} catch {
			/* */
		}
	});

	pi.on("agent_end", async event => {
		try {
			if (
				event &&
				typeof event === "object" &&
				"willContinue" in event &&
				(event as { willContinue?: boolean }).willContinue
			) {
				return;
			}
			const messages =
				event && typeof event === "object" && "messages" in event
					? ((event as { messages?: unknown[] }).messages || [])
					: [];
			await closeActive(messages, "bridge_agent_end");
		} catch {
			/* */
		}
	});

	pi.registerCommand("z0int-bridge-status", {
		description: "Show resident z0int bridge worker generation/build",
		async handler(_args, ctx) {
			try {
				const h = await ensureWorker();
				const st = await request(h, { op: "status" }, 5000);
				ctx.ui.notify(
					`z0int bridge: gen=${st.generation} build=${st.build_id} id=${st.instance_id} protocol=${st.protocol}`,
					"info",
				);
			} catch (e) {
				ctx.ui.notify(String(e), "error");
			}
		},
	});

	pi.registerCommand("z0int-bridge-reload", {
		description: "Hot-reload resident z0int bridge worker (same as /reload-plugins intercept)",
		async handler(_args, ctx) {
			const result = await reload("z0int-bridge-reload-cmd");
			ctx.ui.notify(
				result.ok
					? `z0int bridge → generation ${result.generation} build=${result.build_id}`
					: `reload failed: ${result.error}`,
				result.ok ? "info" : "error",
			);
		},
	});

	pi.registerCommand("z0int-close", {
		description: "Close active z0int turn with optional --verified",
		async handler(args, ctx) {
			const turn = activeTurn;
			if (!turn) {
				ctx.ui.notify("z0int close: no active turn in this session", "warning");
				return;
			}
			const parts = String(args || "").trim().split(/\s+/).filter(Boolean);
			let measured: number | undefined;
			let verified = false;
			for (let i = 0; i < parts.length; i++) {
				if (parts[i] === "--measured" && parts[i + 1]) measured = Number(parts[++i]);
				if (parts[i] === "--verified") verified = true;
			}
			try {
				const h = await ensureWorker();
				const closed = await request(h, {
					op: "turn_close",
					trace_id: turn.traceId,
					session_id: turn.sessionId,
					omp_pid: process.pid,
					payload: {
						measured: measured ?? null,
						execution_completed: true,
						verified_success: verified ? true : null,
						source: verified ? "bridge_verified" : "z0int-close-cmd",
						verification_source: verified ? "operator" : null,
					},
				});
				if (activeTurn?.traceId === turn.traceId) activeTurn = null;
				ctx.ui.notify(
					`z0int close: ${JSON.stringify({ ok: closed.ok !== false, trace: turn.traceId, gen: h.generation })}`,
					closed.ok === false ? "error" : "info",
				);
			} catch (e) {
				ctx.ui.notify(String(e), "error");
			}
		},
	});
}

export { reload, ensureWorker, request, BRIDGE_PROTOCOL, publishShadowTransport };
