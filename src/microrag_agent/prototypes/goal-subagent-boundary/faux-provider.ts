import {
	createAssistantMessageEventStream,
	fauxAssistantMessage,
	fauxToolCall,
	type Context,
	type Model,
	type SimpleStreamOptions,
} from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function contextText(context: Context): string {
	return context.messages
		.flatMap((message) => (Array.isArray(message.content) ? message.content : []))
		.filter((part): part is { type: "text"; text: string } => part.type === "text")
		.map((part) => part.text)
		.join("\n");
}

function goalId(context: Context): string | undefined {
	return /<goal_id>\s*([^<\s]+)\s*<\/goal_id>/u.exec(contextText(context))?.[1];
}

export default function prototypeFauxProvider(pi: ExtensionAPI) {
	const streamSimple = (
		model: Model,
		context: Context,
		options?: SimpleStreamOptions,
	) => {
		const stream = createAssistantMessageEventStream();
		const respond = () => {
			const id = goalId(context);
			const baseMessage = !id
				? fauxAssistantMessage("ordinary child turn completed without an active goal")
				: process.env.PROTOTYPE_OUTCOME === "blocked"
					? fauxAssistantMessage(
					fauxToolCall("goal_blocked", {
						goal_id: id,
						reason: "prototype external dependency",
						evidence: "the same synthetic dependency was observed on three turns",
						repeated_turns: 3,
					}),
					{ stopReason: "toolUse" },
					)
					: fauxAssistantMessage(
				fauxToolCall("goal_complete", {
					goal_id: id,
					summary: "prototype objective completed deterministically",
				}),
				{ stopReason: "toolUse" },
					);
			const message = {
				...baseMessage,
				api: model.api,
				provider: model.provider,
				model: model.id,
			};
			stream.push({ type: "start", partial: { ...message, content: [] } });
			stream.push({
				type: "done",
				reason: message.stopReason === "toolUse" ? "toolUse" : "stop",
				message,
			});
		};

		if (process.env.PROTOTYPE_OUTCOME !== "cancel") {
			setTimeout(respond, 0);
			return stream;
		}

		const partial = {
			...fauxAssistantMessage(""),
			api: model.api,
			provider: model.provider,
			model: model.id,
		};
		stream.push({ type: "start", partial });
		const timer = setInterval(() => {
			if (!options?.signal?.aborted) return;
			clearInterval(timer);
			const error = {
				...partial,
				stopReason: "aborted" as const,
				errorMessage: "prototype parent cancellation",
			};
			stream.push({ type: "error", reason: "aborted", error });
		}, 20);
		return stream;
	};

	pi.registerProvider("prototype-faux", {
		name: "Prototype Faux",
		baseUrl: "http://localhost:0",
		apiKey: "prototype-key",
		api: "prototype-faux",
		streamSimple,
		models: [
			{
				id: "faux-1",
				name: "Prototype Faux",
				api: "prototype-faux",
				reasoning: false,
				input: ["text"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				contextWindow: 128_000,
				maxTokens: 16_384,
			},
		],
	});
}
