'use strict'

// The Contributor Licence Agreement check, run by .github/workflows/cla.yml through
// actions/github-script. It reads the pull request through the API only: it never checks out,
// installs or runs the pull request's code. Comment text, commit metadata and names are untrusted;
// they are only compared with fixed values or counted, and never echoed into the bot's comment
// apart from GitHub user names (letters, digits and hyphens) and commit SHAs (hex).
//
// Signatures live in signatures/cla.json on the cla-signatures branch, in the format the
// earlier contributor-assistant/github-action wrote, so every past signature stays valid:
//   { "signedContributors": [ { "name", "id", "comment_id", "created_at", "repoId", "pullRequestNo" } ] }
// A contributor is recognised by their GitHub account id, not their user name, which can change.

const SIGN_SENTENCE = 'I have read the CLA Document and I hereby sign the CLA'
const SIGNATURES_BRANCH = 'cla-signatures'
const SIGNATURES_PATH = 'signatures/cla.json'
const ALLOWLIST = new Set(['whoispasindu', 'dependabot[bot]', 'github-actions[bot]'])
const BOT_LOGIN = 'github-actions[bot]'
const MARKER = '<!-- sitesense-cla -->'
// The earlier action's comments, updated in place on pull requests opened before the switch.
const LEGACY_MARKER = 'CLA Assistant Lite bot'
// The pull request commits API lists at most 250 commits; past that, fail rather than guess.
const MAX_COMMITS = 250
const WRITE_ATTEMPTS = 3
const UNLINKED_HELP =
  'https://docs.github.com/en/pull-requests/committing-changes-to-your-project/troubleshooting-commits/why-are-my-commits-linked-to-the-wrong-user'

const normalise = (text) =>
  String(text ?? '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/[.!]$/, '')
    .toLowerCase()

/** True when a comment is the signing sentence: whole comment, any case, spacing or final full stop. */
function isSignature(body) {
  return normalise(body) === normalise(SIGN_SENTENCE)
}

/**
 * Decides who still has to sign. Pure: takes what the API returned and changes nothing.
 * @param {object} input
 * @param {Array} input.commits pulls.listCommits items ({ sha, author: { id, login } | null })
 * @param {Array} input.signatures the signedContributors array from the signatures file
 * @param {Array} input.comments issues.listComments items on the pull request, oldest first
 * @param {number} input.repoId @param {number} input.pullRequestNo
 */
function evaluate({ commits, signatures, comments, repoId, pullRequestNo, allowlist = ALLOWLIST }) {
  const authors = new Map()
  const unlinked = []
  for (const commit of commits) {
    const author = commit.author
    if (!author || typeof author.id !== 'number' || !author.login) {
      unlinked.push(String(commit.sha).slice(0, 7))
    } else if (!allowlist.has(author.login) && !authors.has(author.id)) {
      authors.set(author.id, { id: author.id, login: author.login })
    }
  }

  const signedIds = new Set(signatures.map((entry) => entry.id))
  const newSignatures = []
  for (const comment of comments) {
    const user = comment.user
    if (!user || !authors.has(user.id) || signedIds.has(user.id)) continue
    if (!isSignature(comment.body)) continue
    signedIds.add(user.id)
    newSignatures.push({
      name: user.login,
      id: user.id,
      comment_id: comment.id,
      created_at: comment.created_at,
      repoId,
      pullRequestNo,
    })
  }

  const required = [...authors.values()].sort((a, b) => a.login.localeCompare(b.login))
  const signed = required.filter((author) => signedIds.has(author.id))
  const unsigned = required.filter((author) => !signedIds.has(author.id))
  return {
    required,
    signed,
    unsigned,
    unlinked,
    newSignatures,
    allSigned: unsigned.length === 0 && unlinked.length === 0,
  }
}

/** The bot's comment on the pull request for a result of evaluate(). */
function renderComment(result, documentUrl) {
  const agreement = `[Contributor Licence Agreement](${documentUrl})`
  if (result.allSigned) {
    return `${MARKER}\nAll contributors have signed the ${agreement}. Thank you! ✍️ ✅\n`
  }
  const lines = [
    MARKER,
    `Thank you for your pull request! Before it can be merged, everyone who wrote a commit in it ` +
      `needs to sign the ${agreement}, once. It covers all your later contributions too. To sign, ` +
      `add a comment to this pull request with exactly this sentence:`,
    '',
    '```',
    SIGN_SENTENCE,
    '```',
    '',
  ]
  if (result.required.length > 0) {
    lines.push(`**${result.signed.length}** of **${result.required.length}** commit authors have signed.`, '')
    for (const author of result.signed) lines.push(`- ✅ ${author.login}`)
    for (const author of result.unsigned) lines.push(`- ❌ @${author.login}`)
    lines.push('')
  }
  if (result.unlinked.length > 0) {
    const count = result.unlinked.length
    const shown = result.unlinked.slice(0, 10).map((sha) => `\`${sha}\``).join(', ')
    const more = count > 10 ? ` and ${count - 10} more` : ''
    lines.push(
      `${count === 1 ? '1 commit is' : `${count} commits are`} not linked to a GitHub account ` +
        `(${shown}${more}), so their author cannot sign. [Add the commit email address to your ` +
        `GitHub account](${UNLINKED_HELP}), or rewrite the commits with an address that is on it.`,
      '',
    )
  }
  lines.push('<sub>Comment **recheck** to run this check again.</sub>', '')
  return lines.join('\n')
}

async function readSignatures(github, { owner, repo }) {
  let data
  try {
    ;({ data } = await github.rest.repos.getContent({
      owner,
      repo,
      path: SIGNATURES_PATH,
      ref: SIGNATURES_BRANCH,
    }))
  } catch (error) {
    if (error.status === 404) return { file: { signedContributors: [] }, sha: undefined }
    throw error
  }
  if (Array.isArray(data) || data.type !== 'file' || data.encoding !== 'base64') {
    throw new Error(`${SIGNATURES_PATH} on ${SIGNATURES_BRANCH} is not a readable file`)
  }
  const file = JSON.parse(Buffer.from(data.content, 'base64').toString('utf8'))
  const entries = file && file.signedContributors
  if (!Array.isArray(entries) || !entries.every((e) => e && typeof e.id === 'number')) {
    throw new Error(`${SIGNATURES_PATH} on ${SIGNATURES_BRANCH} is not in the expected format`)
  }
  return { file, sha: data.sha }
}

/** Adds the new signatures, re-reading and retrying if another run wrote the file meanwhile. */
async function saveSignatures(github, { owner, repo }, newSignatures, pullRequestNo, core) {
  for (let attempt = 1; ; attempt++) {
    const { file, sha } = await readSignatures(github, { owner, repo })
    const known = new Set(file.signedContributors.map((entry) => entry.id))
    const toAdd = newSignatures.filter((entry) => !known.has(entry.id))
    if (toAdd.length === 0) return
    file.signedContributors.push(...toAdd)
    const names = toAdd.map((entry) => entry.name).join(', ')
    try {
      await github.rest.repos.createOrUpdateFileContents({
        owner,
        repo,
        path: SIGNATURES_PATH,
        branch: SIGNATURES_BRANCH,
        message: `${names} ${toAdd.length === 1 ? 'has' : 'have'} signed the CLA in ${owner}/${repo}#${pullRequestNo}`,
        content: Buffer.from(`${JSON.stringify(file, null, 2)}\n`, 'utf8').toString('base64'),
        ...(sha ? { sha } : {}),
      })
      core.info(`Recorded the signature of ${names}.`)
      return
    } catch (error) {
      const conflict = error.status === 409 || error.status === 422
      if (!conflict || attempt >= WRITE_ATTEMPTS) throw error
      core.info(`The signatures file changed meanwhile; trying again (${attempt}).`)
    }
  }
}

function findBotComment(comments) {
  return comments.find(
    (comment) =>
      comment.user &&
      comment.user.login === BOT_LOGIN &&
      typeof comment.body === 'string' &&
      (comment.body.includes(MARKER) || comment.body.includes(LEGACY_MARKER)),
  )
}

/**
 * The check: for a pull_request_target or issue_comment event on a pull request. Records new
 * signatures, keeps the bot's comment up to date, and fails until every commit author has signed.
 */
async function checkPullRequest({ github, context, core }) {
  const { owner, repo } = context.repo
  const pullRequestNo = context.issue.number
  const repoId = context.payload.repository.id

  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: pullRequestNo })
  if (pr.commits > MAX_COMMITS) {
    core.setFailed(
      `This pull request has ${pr.commits} commits; the CLA check reads at most ${MAX_COMMITS}. ` +
        'Please squash it into fewer commits.',
    )
    return undefined
  }

  const [commits, comments, { file }] = await Promise.all([
    github.paginate(github.rest.pulls.listCommits, { owner, repo, pull_number: pullRequestNo, per_page: 100 }),
    github.paginate(github.rest.issues.listComments, { owner, repo, issue_number: pullRequestNo, per_page: 100 }),
    readSignatures(github, { owner, repo }),
  ])

  const result = evaluate({ commits, signatures: file.signedContributors, comments, repoId, pullRequestNo })
  if (result.newSignatures.length > 0) {
    await saveSignatures(github, { owner, repo }, result.newSignatures, pullRequestNo, core)
  }

  const body = renderComment(result, `https://github.com/${owner}/${repo}/blob/HEAD/CLA.md`)
  const existing = findBotComment(comments)
  if (existing) {
    if (existing.body !== body) {
      await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body })
    }
  } else if (!result.allSigned) {
    await github.rest.issues.createComment({ owner, repo, issue_number: pullRequestNo, body })
  }

  if (result.allSigned) {
    core.info('Every commit author has signed the CLA, or is on the allowlist.')
  } else {
    const waiting = [...result.unsigned.map((author) => author.login)]
    if (result.unlinked.length > 0) waiting.push(`${result.unlinked.length} unlinked commit(s)`)
    core.setFailed(`Waiting for the CLA: ${waiting.join(', ')}.`)
  }
  return result
}

/**
 * After a signing (or recheck) comment made everyone signed, re-runs the pull request's own failed
 * CLA run, so the check on the pull request's head commit turns green. A cancelled run (a pending
 * run displaced by a newer one in the same concurrency group) is re-run too.
 */
async function rerunPullRequestCheck({ github, context, core }) {
  const { owner, repo } = context.repo
  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: context.issue.number })
  const { data: current } = await github.rest.actions.getWorkflowRun({ owner, repo, run_id: context.runId })
  const { data } = await github.rest.actions.listWorkflowRuns({
    owner,
    repo,
    workflow_id: current.workflow_id,
    event: 'pull_request_target',
    branch: pr.head.ref,
    per_page: 20,
  })
  // Newest first. Prefer the run for the current head commit; branch names are not unique
  // across forks.
  const runs = data.workflow_runs
  const run = runs.find((candidate) => candidate.head_sha === pr.head.sha) || runs[0]
  if (!run) {
    core.info('No CLA run found for this pull request.')
    return undefined
  }
  if (run.status !== 'completed' || !['failure', 'cancelled'].includes(run.conclusion)) {
    core.info(`The pull request's CLA run ${run.id} is ${run.status} (${run.conclusion}); nothing to re-run.`)
    return undefined
  }
  await github.rest.actions.reRunWorkflow({ owner, repo, run_id: run.id })
  core.info(`Re-ran CLA run ${run.id}.`)
  return run.id
}

module.exports = {
  ALLOWLIST,
  MARKER,
  SIGN_SENTENCE,
  SIGNATURES_BRANCH,
  SIGNATURES_PATH,
  checkPullRequest,
  evaluate,
  isSignature,
  renderComment,
  rerunPullRequestCheck,
}
