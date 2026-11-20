'use strict'

// Tests for cla.cjs against a fake GitHub API. Run: node --test .github/scripts/cla.test.cjs

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')

const cla = require('./cla.cjs')

const REPO = { owner: 'whoispasindu', repo: 'SiteSense' }
const SENTENCE = cla.SIGN_SENTENCE
const ALICE = { id: 101, login: 'alice' }
const BOB = { id: 102, login: 'bob' }
const OWNER = { id: 70275854, login: 'whoispasindu' }
const BOT = { id: 41898282, login: 'github-actions[bot]' }

const commit = (sha, author) => ({ sha, author, commit: { author: { name: 'x', email: 'x@example.com' } } })
const comment = (id, user, body) => ({ id, user, body, created_at: `2026-11-20T10:00:${String(id % 60).padStart(2, '0')}Z` })
const encode = (value) => Buffer.from(JSON.stringify(value), 'utf8').toString('base64')
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { status })

/** A fake of the parts of github-script's `github` client that cla.cjs uses, recording writes. */
function fakeGitHub({ commits = [], comments = [], signatures = [], fileMissing = false, prCommits, conflicts = 0, runs = [] } = {}) {
  const state = {
    file: fileMissing ? undefined : { signedContributors: signatures },
    fileSha: 'sha-0',
    comments: comments.map((c) => ({ ...c })),
    writes: [],
    created: [],
    updated: [],
    reruns: [],
    conflictsLeft: conflicts,
  }
  const github = {
    paginate: async (method, params) => (await method(params)).data,
    rest: {
      pulls: {
        get: async () => ({
          data: { number: 7, commits: prCommits ?? commits.length, head: { ref: 'fix-typo', sha: 'head-sha' } },
        }),
        listCommits: async () => ({ data: commits }),
      },
      issues: {
        listComments: async () => ({ data: state.comments }),
        createComment: async ({ body }) => {
          state.created.push(body)
          return { data: {} }
        },
        updateComment: async ({ comment_id, body }) => {
          state.updated.push({ comment_id, body })
          return { data: {} }
        },
      },
      repos: {
        getContent: async ({ path, ref }) => {
          assert.equal(path, 'signatures/cla.json')
          assert.equal(ref, 'cla-signatures')
          if (!state.file) throw httpError(404)
          return { data: { type: 'file', encoding: 'base64', content: encode(state.file), sha: state.fileSha } }
        },
        createOrUpdateFileContents: async (params) => {
          assert.equal(params.branch, 'cla-signatures')
          if (state.conflictsLeft > 0) {
            state.conflictsLeft -= 1
            // Another run signed meanwhile: the file and its sha change under us.
            state.file.signedContributors.push({ name: 'carol', id: 103 })
            state.fileSha = `${state.fileSha}+`
            throw httpError(409)
          }
          if (state.file) assert.equal(params.sha, state.fileSha)
          else assert.equal(params.sha, undefined)
          const text = Buffer.from(params.content, 'base64').toString('utf8')
          state.file = JSON.parse(text)
          state.fileSha = `${state.fileSha}*`
          state.writes.push({ message: params.message, text })
          return { data: {} }
        },
      },
      actions: {
        getWorkflowRun: async ({ run_id }) => ({ data: { id: run_id, workflow_id: 555 } }),
        listWorkflowRuns: async (params) => {
          assert.deepEqual(
            { workflow_id: params.workflow_id, event: params.event, branch: params.branch },
            { workflow_id: 555, event: 'pull_request_target', branch: 'fix-typo' },
          )
          return { data: { workflow_runs: runs } }
        },
        reRunWorkflow: async ({ run_id }) => {
          state.reruns.push(run_id)
          return { data: {} }
        },
      },
    },
  }
  return { github, state }
}

function fakeCore() {
  const core = { failed: undefined, logs: [] }
  core.info = (message) => core.logs.push(message)
  core.setFailed = (message) => {
    core.failed = message
  }
  return core
}

const context = { repo: REPO, issue: { number: 7 }, payload: { repository: { id: 999 } }, runId: 4242 }

describe('isSignature', () => {
  it('accepts the sentence in any case and spacing, with a final full stop', () => {
    assert.ok(cla.isSignature(SENTENCE))
    assert.ok(cla.isSignature(`  ${SENTENCE.toUpperCase()}.\n`))
    assert.ok(cla.isSignature('I have read the CLA Document and\nI hereby   sign the CLA'))
  })

  it('refuses anything more or less than the sentence', () => {
    assert.ok(!cla.isSignature(`> ${SENTENCE}`))
    assert.ok(!cla.isSignature(`${SENTENCE}, but not really`))
    assert.ok(!cla.isSignature(`I have not read the CLA Document and I hereby sign the CLA`))
    assert.ok(!cla.isSignature('recheck'))
    assert.ok(!cla.isSignature(undefined))
  })
})

describe('evaluate', () => {
  const base = { comments: [], signatures: [], repoId: 999, pullRequestNo: 7 }

  it('skips allowlisted authors and counts each author once', () => {
    const result = cla.evaluate({
      ...base,
      commits: [commit('a1', OWNER), commit('a2', { id: 49699333, login: 'dependabot[bot]' }), commit('a3', ALICE), commit('a4', ALICE)],
    })
    assert.deepEqual(result.required, [ALICE])
    assert.deepEqual(result.unsigned, [ALICE])
    assert.equal(result.allSigned, false)
  })

  it('treats signatures by account id, so a renamed account stays signed', () => {
    const result = cla.evaluate({
      ...base,
      commits: [commit('a1', { id: ALICE.id, login: 'alice-renamed' })],
      signatures: [{ name: 'alice', id: ALICE.id }],
    })
    assert.equal(result.allSigned, true)
    assert.deepEqual(result.newSignatures, [])
  })

  it('records a signing comment by an unsigned commit author, in the existing file format', () => {
    const result = cla.evaluate({
      ...base,
      commits: [commit('a1', ALICE), commit('a2', BOB)],
      comments: [comment(1, ALICE, 'Looks good'), comment(2, ALICE, SENTENCE), comment(3, ALICE, SENTENCE)],
    })
    assert.deepEqual(result.newSignatures, [
      { name: 'alice', id: 101, comment_id: 2, created_at: '2026-11-20T10:00:02Z', repoId: 999, pullRequestNo: 7 },
    ])
    assert.deepEqual(result.signed, [ALICE])
    assert.deepEqual(result.unsigned, [BOB])
  })

  it('ignores signing comments from people who wrote no commit here, and the bot', () => {
    const result = cla.evaluate({
      ...base,
      commits: [commit('a1', ALICE)],
      comments: [comment(1, BOB, SENTENCE), comment(2, BOT, SENTENCE), comment(3, { id: ALICE.id + 1000, login: 'alice' }, SENTENCE)],
    })
    assert.deepEqual(result.newSignatures, [])
    assert.deepEqual(result.unsigned, [ALICE])
  })

  it('fails while a commit is not linked to a GitHub account', () => {
    const result = cla.evaluate({ ...base, commits: [commit('abcdef0123', null), commit('a2', OWNER)] })
    assert.deepEqual(result.unlinked, ['abcdef0'])
    assert.deepEqual(result.required, [])
    assert.equal(result.allSigned, false)
  })
})

describe('renderComment', () => {
  it('asks unsigned authors to sign and does not echo commit author names', () => {
    const result = cla.evaluate({
      commits: [commit('a1', ALICE), commit('a2', BOB), { sha: 'feedbeef99', author: null, commit: { author: { name: '@everyone [x](https://evil.example)' } } }],
      signatures: [{ id: ALICE.id }],
      comments: [],
      repoId: 999,
      pullRequestNo: 7,
    })
    const body = cla.renderComment(result, 'https://github.com/whoispasindu/SiteSense/blob/HEAD/CLA.md')
    assert.ok(body.startsWith(cla.MARKER))
    assert.ok(body.includes(`\`\`\`\n${SENTENCE}\n\`\`\``))
    assert.ok(body.includes('**1** of **2** commit authors have signed.'))
    assert.ok(body.includes('- ✅ alice'))
    assert.ok(body.includes('- ❌ @bob'))
    assert.ok(body.includes('`feedbee`'))
    assert.ok(!body.includes('@everyone'))
    assert.ok(!body.includes('evil.example'))
  })
})

describe('checkPullRequest', () => {
  it('records a new signature, keeping the earlier ones, and passes', async () => {
    const earlier = { name: 'bob', id: BOB.id, comment_id: 1, created_at: '2026-01-01T00:00:00Z', repoId: 999, pullRequestNo: 3 }
    const { github, state } = fakeGitHub({
      commits: [commit('a1', ALICE), commit('a2', BOB)],
      signatures: [earlier],
      comments: [comment(5, BOT, `${cla.MARKER}\nold`), comment(6, ALICE, SENTENCE)],
    })
    const core = fakeCore()
    const result = await cla.checkPullRequest({ github, context, core })

    assert.equal(result.allSigned, true)
    assert.equal(core.failed, undefined)
    assert.equal(state.writes.length, 1)
    assert.equal(state.writes[0].message, 'alice has signed the CLA in whoispasindu/SiteSense#7')
    assert.deepEqual(JSON.parse(state.writes[0].text), {
      signedContributors: [
        earlier,
        { name: 'alice', id: 101, comment_id: 6, created_at: '2026-11-20T10:00:06Z', repoId: 999, pullRequestNo: 7 },
      ],
    })
    assert.equal(state.created.length, 0)
    assert.equal(state.updated.length, 1)
    assert.equal(state.updated[0].comment_id, 5)
    assert.ok(state.updated[0].body.includes('All contributors have signed'))
  })

  it('comments once and fails while someone has not signed', async () => {
    const { github, state } = fakeGitHub({ commits: [commit('a1', ALICE)] })
    const core = fakeCore()
    await cla.checkPullRequest({ github, context, core })
    assert.equal(state.created.length, 1)
    assert.match(core.failed, /Waiting for the CLA: alice/)
    assert.equal(state.writes.length, 0)

    // A second run with the comment now present edits nothing, since nothing changed.
    state.comments.push(comment(9, BOT, state.created[0]))
    await cla.checkPullRequest({ github, context, core: fakeCore() })
    assert.equal(state.created.length, 1)
    assert.equal(state.updated.length, 0)
  })

  it('updates a comment left by the earlier CLA action', async () => {
    const { github, state } = fakeGitHub({
      commits: [commit('a1', ALICE)],
      comments: [comment(4, BOT, '**CLA Assistant Lite bot:** <br/>Thank you for your submission')],
    })
    await cla.checkPullRequest({ github, context, core: fakeCore() })
    assert.equal(state.created.length, 0)
    assert.equal(state.updated[0].comment_id, 4)
  })

  it('stays silent when every author is allowlisted', async () => {
    const { github, state } = fakeGitHub({ commits: [commit('a1', OWNER), commit('a2', { id: 49699333, login: 'dependabot[bot]' })] })
    const core = fakeCore()
    await cla.checkPullRequest({ github, context, core })
    assert.equal(core.failed, undefined)
    assert.deepEqual([state.created, state.updated, state.writes], [[], [], []])
  })

  it('re-reads and retries when another run wrote the signatures file first', async () => {
    const { github, state } = fakeGitHub({ commits: [commit('a1', ALICE)], comments: [comment(6, ALICE, SENTENCE)], conflicts: 1 })
    await cla.checkPullRequest({ github, context, core: fakeCore() })
    assert.deepEqual(
      state.file.signedContributors.map((entry) => entry.name),
      ['carol', 'alice'],
    )
  })

  it('creates the signatures file if it is missing', async () => {
    const { github, state } = fakeGitHub({ commits: [commit('a1', ALICE)], comments: [comment(6, ALICE, SENTENCE)], fileMissing: true })
    await cla.checkPullRequest({ github, context, core: fakeCore() })
    assert.deepEqual(state.file.signedContributors.map((entry) => entry.id), [ALICE.id])
  })

  it('fails closed on a malformed signatures file', async () => {
    const { github, state } = fakeGitHub({ commits: [commit('a1', ALICE)] })
    state.file = { signedContributors: [{ name: 'alice' }] }
    await assert.rejects(cla.checkPullRequest({ github, context, core: fakeCore() }), /expected format/)
  })

  it('fails rather than guess when the pull request has more commits than the API lists', async () => {
    const { github } = fakeGitHub({ commits: [commit('a1', ALICE)], prCommits: 251 })
    const core = fakeCore()
    await cla.checkPullRequest({ github, context, core })
    assert.match(core.failed, /251 commits/)
  })
})

describe('rerunPullRequestCheck', () => {
  it('re-runs the failed run for the head commit, not an older one on the same branch', async () => {
    const { github, state } = fakeGitHub({
      runs: [
        { id: 3, head_sha: 'other-fork-sha', status: 'completed', conclusion: 'failure' },
        { id: 2, head_sha: 'head-sha', status: 'completed', conclusion: 'failure' },
        { id: 1, head_sha: 'old-sha', status: 'completed', conclusion: 'failure' },
      ],
    })
    assert.equal(await cla.rerunPullRequestCheck({ github, context, core: fakeCore() }), 2)
    assert.deepEqual(state.reruns, [2])
  })

  it('re-runs a cancelled run too', async () => {
    const { github, state } = fakeGitHub({ runs: [{ id: 2, head_sha: 'head-sha', status: 'completed', conclusion: 'cancelled' }] })
    await cla.rerunPullRequestCheck({ github, context, core: fakeCore() })
    assert.deepEqual(state.reruns, [2])
  })

  it('leaves a run alone unless it finished and failed', async () => {
    for (const run of [
      { id: 2, head_sha: 'head-sha', status: 'in_progress', conclusion: null },
      { id: 2, head_sha: 'head-sha', status: 'completed', conclusion: 'success' },
    ]) {
      const { github, state } = fakeGitHub({ runs: [run] })
      assert.equal(await cla.rerunPullRequestCheck({ github, context, core: fakeCore() }), undefined)
      assert.deepEqual(state.reruns, [])
    }
  })
})
