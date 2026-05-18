import { describe, expect, test } from 'bun:test'

import { CLI_SYSPROMPT_PREFIXES, getCLISyspromptPrefix } from '../system.js'
import { DEFAULT_AGENT_PROMPT, getSystemPrompt } from '../prompts.js'
import { getCoordinatorSystemPrompt } from '../../coordinator/coordinatorMode.js'

const MICRORAG_IDENTITY = "You are MicroRAG's product conversation agent."

function expectMicroRAGIdentity(text: string): void {
  expect(text).toContain('MicroRAG')
  expect(text).not.toContain('You are Claude Code')
  expect(text).not.toContain("Anthropic's official CLI for Claude")
  expect(text).not.toContain('Claude Agent SDK')
}

describe('MicroRAG product identity prompt patch', () => {
  test('CLI system prompt prefixes use MicroRAG product identity', () => {
    expect(getCLISyspromptPrefix()).toBe(MICRORAG_IDENTITY)
    expect(
      getCLISyspromptPrefix({
        isNonInteractive: true,
        hasAppendSystemPrompt: true,
      }),
    ).toBe(
      "You are MicroRAG's product conversation agent, running in the local agent runtime.",
    )
    expect(
      getCLISyspromptPrefix({
        isNonInteractive: true,
        hasAppendSystemPrompt: false,
      }),
    ).toBe(
      'You are a MicroRAG task agent for the product conversation runtime.',
    )

    for (const prefix of CLI_SYSPROMPT_PREFIXES) {
      expectMicroRAGIdentity(prefix)
    }
  })

  test('simple system prompt path uses MicroRAG product identity', async () => {
    const previous = process.env.CLAUDE_CODE_SIMPLE
    process.env.CLAUDE_CODE_SIMPLE = '1'
    try {
      const prompt = await getSystemPrompt([] as any, 'test-model')
      expect(prompt).toHaveLength(1)
      expect(prompt[0]).toContain(MICRORAG_IDENTITY)
      expect(prompt[0]).toContain('CWD:')
      expect(prompt[0]).toContain('Date:')
      expectMicroRAGIdentity(prompt[0])
    } finally {
      if (previous === undefined) {
        delete process.env.CLAUDE_CODE_SIMPLE
      } else {
        process.env.CLAUDE_CODE_SIMPLE = previous
      }
    }
  })

  test('default subagent prompt uses MicroRAG task agent identity', () => {
    expect(DEFAULT_AGENT_PROMPT).toContain('MicroRAG')
    expect(DEFAULT_AGENT_PROMPT).toContain('use the tools available')
    expect(DEFAULT_AGENT_PROMPT).toContain('respond with a concise report')
    expectMicroRAGIdentity(DEFAULT_AGENT_PROMPT)
  })

  test('coordinator prompt uses MicroRAG coordinator identity', () => {
    const prompt = getCoordinatorSystemPrompt()
    expect(prompt).toContain(
      'You are MicroRAG, an AI assistant that orchestrates software engineering tasks across multiple workers.',
    )
    expect(prompt).toContain('## 1. Your Role')
    expectMicroRAGIdentity(prompt)
  })
})
