/**
 * Shadow + private live learning stream. Native Jev remains the teacher.
 * Never injects skill_relevance.
 *
 * Cascade (gen-0 safe offload):
 *   DELEGATE any conf → local (~98% pred precision)
 *   high-conf EXECUTE → local
 *   else → escalate (jev / openjev fallback)
 *
 * Every row: trace_id, session_id, fly probs, jev label/p, route, latency.
 * Written under ~/.z0int/ only (stream + shadow).
 */
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const SHADOW_LOG = join(homedir(), ".z0int", "shadow", "jev-fly.jsonl");
const STREAM_RAW = join(homedir(), ".z0int", "stream", "raw.jsonl");
const STREAM_HI = join(homedir(), ".z0int", "stream", "high_info.jsonl");
const PY =
	process.env.EVOLUTION_LAB_PYTHON ||
	"/workspace/evolution-lab/.venv/bin/python";
const CWD = process.env.EVOLUTION_LAB_ROOT || "/workspace/evolution-lab";
const WEAK: Record<string, true> = { EDIT: true, WEB: true, VERIFY: true, ABSTAIN: true };

type PyResult = { code: number; stdout: string; stderr: string };
type Jsonish = Record<string, unknown> & { ok?: boolean; error?: string; label?: unknown; p?: unknown };

async function runPy(args: string[], timeoutMs: number): Promise<PyResult> {
	const { promise, resolve } = Promise.withResolvers<PyResult>();
	const child = spawn(PY, args, { cwd: CWD, stdio: ["ignore", "pipe", "pipe"] });
	let stdout = "";
	let stderr = "";
	const timer = setTimeout(() => {
		child.kill("SIGKILL");
	}, timeoutMs);
	child.stdout.on("data", d => {
		stdout += String(d);
	});
	child.stderr.on("data", d => {
		stderr += String(d);
	});
	child.on("close", code => {
		clearTimeout(timer);
		resolve({ code: code ?? 1, stdout, stderr });
	});
	child.on("error", err => {
		clearTimeout(timer);
		resolve({ code: 1, stdout: "", stderr: String(err) });
	});
	return promise;
}

function parseJson(r: PyResult): Jsonish {
	if (r.code !== 0) return { ok: false, error: "nonzero" };
	try {
		const value: unknown = JSON.parse(r.stdout);
		if (value && typeof value === "object") return value as Jsonish;
		return { ok: false, error: "json" };
	} catch {
		return { ok: false, error: "json" };
	}
}

function isHighInfo(row: {
	disagree: boolean | null;
	route: string | null;
	label: unknown;
}): boolean {
	if (row.disagree) return true;
	if (row.route === "escalate") return true;
	if (typeof row.label === "string" && WEAK[row.label]) return true;
	return false;
}

async function shadow(prompt: string, sessionId: string | undefined): Promise<void> {
	const t0 = Date.now();
	const [decideRaw, jevRaw] = await Promise.all([
		runPy(["-m", "evolution_lab", "next-action-decide", prompt], 8000),
		runPy(["-m", "evolution_lab", "jev-predict", prompt], 8000),
	]);
	const decision = parseJson(decideRaw);
	const jevOut = parseJson(jevRaw);
	const latencyMs = Date.now() - t0;
	const fly =
		decision.prediction && typeof decision.prediction === "object"
			? (decision.prediction as Jsonish)
			: decision;
	const route = typeof decision.route === "string" ? decision.route : null;
	const traceId = randomUUID().replaceAll("-", "");
	const flyLabel = fly.label;
	const jevLabel = jevOut.label;
	const disagree =
		Boolean(fly.ok) && Boolean(jevOut.ok) && flyLabel !== undefined && jevLabel !== undefined
			? flyLabel !== jevLabel
			: null;

	let teacher: Jsonish | null = null;
	if (route === "local") {
		teacher = { source: "next_action_local", label: decision.label, p: decision.p };
	} else if (route === "escalate" && jevOut.ok) {
		teacher = { source: jevOut.source, label: jevOut.label, p: jevOut.p };
	}

	const shadowRow = {
		ts: Date.now() / 1000,
		trace_id: traceId,
		session_id: sessionId ?? null,
		prompt: prompt.slice(0, 400),
		decision: decision.ok
			? {
					route: decision.route,
					reason: decision.reason,
					escalate_to: decision.escalate_to,
					fallback: decision.fallback,
					label: decision.label,
					p: decision.p,
					margin: decision.margin,
				}
			: decision,
		next_action: fly,
		jev: jevOut,
		teacher,
		disagree,
		latency_ms: latencyMs,
		generation: 0,
	};
	mkdirSync(join(homedir(), ".z0int", "shadow"), { recursive: true });
	appendFileSync(SHADOW_LOG, JSON.stringify(shadowRow) + "\n");

	const streamRow = {
		schema: "flyforge.live_decision.v1",
		ts: shadowRow.ts,
		trace_id: traceId,
		session_id: sessionId ?? process.env.OMP_SESSION_ID ?? process.env.HERMES_SESSION_ID ?? null,
		prompt: prompt.slice(0, 400),
		decision: shadowRow.decision,
		fly: {
			label: fly.label,
			p: fly.p,
			margin: fly.margin,
			probs: fly.probs,
			source: fly.source,
			n_params: fly.n_params,
		},
		teachers: jevOut.ok
			? { jev: { label: jevOut.label, p: jevOut.p, source: jevOut.source } }
			: {},
		disagree,
		latency_ms: latencyMs,
		generation: 0,
		high_info: isHighInfo({ disagree, route, label: decision.label ?? fly.label }),
	};
	mkdirSync(join(homedir(), ".z0int", "stream"), { recursive: true });
	appendFileSync(STREAM_RAW, JSON.stringify(streamRow) + "\n");
	if (streamRow.high_info) {
		appendFileSync(STREAM_HI, JSON.stringify(streamRow) + "\n");
	}
}

export default function flyforgeJevShadow(pi: ExtensionAPI) {
	pi.setLabel("Fly live stream (log only)");
	pi.on("before_agent_start", (event, ctx) => {
		const prompt =
			event && typeof event === "object" && "prompt" in event
				? String((event as { prompt?: unknown }).prompt ?? "").trim()
				: "";
		if (!prompt || prompt.startsWith("/")) return;
		const sessionId =
			ctx && typeof ctx === "object" && "sessionId" in ctx
				? String((ctx as { sessionId?: unknown }).sessionId ?? "")
				: process.env.OMP_SESSION_ID;
		void shadow(prompt, sessionId || undefined);
	});
}

export { shadow };
