import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const prototypeDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(prototypeDir, "../../../..");
const piRoot = process.env.PI_SNAPSHOT_ROOT
	? resolve(process.env.PI_SNAPSHOT_ROOT)
	: join(repoRoot, "参考项目/pi");
const cliPath = join(piRoot, "packages/coding-agent/dist/cli.js");
const fauxExtension = join(prototypeDir, "faux-provider.ts");
const goalExtension = join(
	prototypeDir,
	"node_modules/@narumitw/pi-goal/src/goal.ts",
);
const piArgsModule = await import(
	join(prototypeDir, "node_modules/pi-subagents/src/runs/shared/pi-args.ts")
);
const { buildPiArgs, cleanupTempDir } = piArgsModule;

const delegatedTask = 'Inspect  "docs/quoted path.md"  and report exact evidence';
const scratch = mkdtempSync(join(tmpdir(), "pi-goal-subagent-boundary-"));

function requirePath(path, label) {
	if (!existsSync(path)) throw new Error(`${label} not found: ${path}`);
}

function jsonLines(value) {
	return value
		.split("\n")
		.filter(Boolean)
		.flatMap((line) => {
			try {
				return [JSON.parse(line)];
			} catch {
				return [];
			}
		});
}

function goalEntries(sessionFile, stdout = "") {
	const persisted = existsSync(sessionFile) ? jsonLines(readFileSync(sessionFile, "utf8")) : [];
	const emitted = jsonLines(stdout)
		.filter((event) => event.type === "entry_appended")
		.map((event) => event.entry);
	return [...persisted, ...emitted].filter(
		(entry) => entry.type === "custom" && entry.customType === "goal-state",
	);
}

function launchArgs(sessionFile, task = delegatedTask) {
	return buildPiArgs({
		baseArgs: ["--offline", "--approve", "--mode", "json", "-p"],
		task,
		sessionEnabled: true,
		sessionFile,
		model: "prototype-faux/faux-1",
		inheritProjectContext: false,
		inheritSkills: false,
		extensions: [fauxExtension, goalExtension],
	});
}

function useRawGoalCommand(built, task = delegatedTask) {
	const args = [...built.args];
	const promptIndex = args.findLastIndex((arg) => arg === `Task: ${task}`);
	if (promptIndex < 0) throw new Error("pi-subagents task prompt was not found");
	args[promptIndex] = `/goal ${task}`;
	return { ...built, args };
}

async function runCli(name, built, outcome) {
	const scenarioCwd = join(scratch, name);
	mkdirSync(scenarioCwd, { recursive: true });
	const child = spawn(process.execPath, [cliPath, ...built.args], {
		cwd: scenarioCwd,
		env: {
			...process.env,
			PI_CODING_AGENT_DIR: join(scratch, `${name}-agent`),
			PROTOTYPE_OUTCOME: outcome,
			...built.env,
		},
		stdio: ["ignore", "pipe", "pipe"],
	});
	let stdout = "";
	let stderr = "";
	child.stdout.setEncoding("utf8");
	child.stderr.setEncoding("utf8");
	child.stdout.on("data", (chunk) => {
		stdout += chunk;
	});
	child.stderr.on("data", (chunk) => {
		stderr += chunk;
	});
	let timedOut = false;
	const softTimer = setTimeout(() => {
		timedOut = true;
		child.kill("SIGTERM");
	}, 5_000);
	const hardTimer = setTimeout(() => child.kill("SIGKILL"), 6_000);
	const exit = await new Promise((resolveExit) => {
		child.once("exit", (code, signal) => resolveExit({ code, signal }));
	});
	clearTimeout(softTimer);
	clearTimeout(hardTimer);
	cleanupTempDir(built.tempDir);
	return { ...exit, stdout, stderr, timedOut };
}

function requireCondition(condition, message) {
	if (!condition) throw new Error(message);
}

requirePath(cliPath, "built Pi CLI (set PI_SNAPSHOT_ROOT when the snapshot is elsewhere)");
requirePath(goalExtension, "pi-goal extension");

try {
	const currentSession = join(scratch, "current.jsonl");
	const currentBuilt = launchArgs(currentSession);
	const current = await runCli("current", currentBuilt, "complete");
	const currentGoals = goalEntries(currentSession);
	requireCondition(current.code === 0 && !current.timedOut, `current launch failed: ${JSON.stringify(current)}`);
	requireCondition(currentGoals.length === 0, "current Task: launch unexpectedly created a goal");

	const completeSession = join(scratch, "complete.jsonl");
	const completeBuilt = useRawGoalCommand(launchArgs(completeSession));
	const complete = await runCli("complete", completeBuilt, "complete");
	const completeGoals = goalEntries(completeSession, complete.stdout);
	const persistedObjective = completeGoals.find((entry) => entry.data?.goal)?.data.goal.text;
	requireCondition(
		complete.timedOut && (complete.signal === "SIGTERM" || complete.signal === "SIGKILL"),
		`raw /goal print-mode failure was not reproduced: ${JSON.stringify(complete)}`,
	);
	requireCondition(
		completeGoals.some((entry) => entry.data?.goal?.status === "active"),
		`raw /goal launch did not persist active goal-state: ${JSON.stringify({ stdout: complete.stdout, stderr: complete.stderr, completeGoals })}`,
	);
	requireCondition(
		persistedObjective !== delegatedTask,
		"prototype task did not expose slash-command objective normalization",
	);

	const injectedExtensions = completeBuilt.args.filter(
		(arg, index, args) => args[index - 1] === "--extension",
	);

	console.log(
		JSON.stringify(
			{
				question: "Can public composition guarantee exact delegated task as child goal?",
				verdict: "no",
				delegatedTask,
				currentLaunch: {
					prompt: currentBuilt.args.at(-1),
					goalStateEntries: currentGoals.length,
				},
				rawGoalLaunch: {
					prompt: completeBuilt.args.at(-1),
					persistedObjective,
					preservedExactly: persistedObjective === delegatedTask,
					states: completeGoals.map((entry) => entry.data?.goal?.status ?? null),
					printModeExitedNaturally: !complete.timedOut,
					terminationSignal: complete.signal,
				},
				injectedExtensions,
				sharedLaunchSink: "pi-subagents buildPiArgs()",
				objectiveLimit: 4_000,
			},
			null,
			2,
		),
	);
} finally {
	rmSync(scratch, { recursive: true, force: true });
}
