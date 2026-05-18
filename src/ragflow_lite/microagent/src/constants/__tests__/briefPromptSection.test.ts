import { describe, expect, test } from 'bun:test'
import { resolve } from 'path'

describe('brief prompt section regression guard', () => {
  test('checks isBriefEnabled is callable before invoking it', async () => {
    const promptsPath = resolve(__dirname, '..', 'prompts.ts')
    const source = await Bun.file(promptsPath).text()

    expect(source).toContain(
      "typeof briefToolModule?.isBriefEnabled !== 'function'",
    )
  })
})
