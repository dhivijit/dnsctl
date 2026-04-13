"""Git manager — auto-managed git repository inside the state directory."""

import logging
from pathlib import Path

from git import Actor, InvalidGitRepositoryError, Repo

from dnsctl.config import GIT_AUTHOR_EMAIL, GIT_AUTHOR_NAME, STATE_DIR

logger = logging.getLogger(__name__)


class GitManager:
    """Manages a git repository in ``~/.dnsctl/`` for version tracking."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._dir = state_dir or STATE_DIR
        self._repo: Repo | None = None

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def auto_init(self) -> Repo:
        """Open or create the git repository.  Idempotent."""
        try:
            self._repo = Repo(self._dir)
        except InvalidGitRepositoryError:
            self._repo = Repo.init(self._dir)
            # Perform an initial commit so HEAD exists — only stage files that exist
            gitignore = self._dir / ".gitignore"
            if gitignore.exists():
                self._repo.index.add([".gitignore"])
            author = Actor(GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL)
            self._repo.index.commit(
                "Initial dnsctl state", author=author, committer=author
            )
            logger.info("Initialised new git repo in %s", self._dir)
        return self._repo

    @property
    def repo(self) -> Repo:
        if self._repo is None:
            return self.auto_init()
        return self._repo

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def commit(self, message: str) -> str | None:
        """Stage all changes in the state directory and commit.

        Returns the commit hex SHA, or ``None`` if there was nothing to commit.
        """
        repo = self.repo
        # Stage everything (respects .gitignore)
        repo.git.add(A=True)

        if not repo.is_dirty(index=True, untracked_files=True):
            logger.debug("Nothing to commit.")
            return None

        author = Actor(GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL)
        c = repo.index.commit(message, author=author, committer=author)
        logger.info("Committed: %s (%s)", message, c.hexsha[:8])
        return c.hexsha

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def log(self, max_count: int = 50) -> list[dict]:
        """Return recent commits as a list of dicts.

        Each entry has:
        - ``title``   — first line of the commit message (safe for table display)
        - ``message`` — full message including any detail body (backward-compatible:
                        old single-line commits have ``title == message``)
        """
        repo = self.repo
        commits = []
        for c in repo.iter_commits(max_count=max_count):
            full = c.message.strip()
            title = full.split("\n")[0]
            commits.append(
                {
                    "sha": c.hexsha,
                    "short_sha": c.hexsha[:8],
                    "title": title,
                    "message": full,
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                }
            )
        return commits

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, commit_sha: str) -> str:
        """Restore the working tree to the state at *commit_sha*.

        Creates a **new** commit so history is never lost.

        Returns the new commit's hex SHA.

        Raises ``ValueError`` if *commit_sha* cannot be resolved.
        """
        from pathlib import Path as _Path

        repo = self.repo
        try:
            target = repo.commit(commit_sha)
        except Exception as exc:
            raise ValueError(f"Cannot resolve commit '{commit_sha}': {exc}") from exc

        head_sha = repo.head.commit.hexsha
        logger.debug(
            "Rollback: target=%s  head=%s  repo=%s",
            target.hexsha[:8], head_sha[:8], self._dir,
        )

        try:
            # ------------------------------------------------------------------
            # Step 1 — delete files that exist in HEAD but not in the target.
            #
            # `git checkout <sha> -- .` only restores files that *exist* in the
            # target tree; it never removes files that were *added* after it.
            # Without this step, a rollback past a sync (new zone file added)
            # would leave the new zone file in place and produce nothing to commit.
            # ------------------------------------------------------------------
            target_paths = {
                item.path
                for item in target.tree.traverse()
                if item.type == "blob"
            }
            head_paths = {
                item.path
                for item in repo.head.commit.tree.traverse()
                if item.type == "blob"
            }
            to_delete = head_paths - target_paths
            logger.debug("Rollback: files to delete (added after target): %s", to_delete)
            for rel in to_delete:
                full = self._dir / _Path(rel)
                if full.exists():
                    logger.debug("Rollback: deleting %s", rel)
                    full.unlink()

            # ------------------------------------------------------------------
            # Step 2 — restore every file from the target tree.
            # ------------------------------------------------------------------
            logger.debug("Rollback: checking out target tree")
            repo.git.checkout(target.hexsha, "--", ".")

            # ------------------------------------------------------------------
            # Step 3 — stage all changes (modifications, deletions, and the
            # explicit file removals from step 1).
            # ------------------------------------------------------------------
            logger.debug("Rollback: staging all changes")
            repo.git.add(A=True)

            # ------------------------------------------------------------------
            # Step 4 — check for staged changes using diff --cached rather than
            # is_dirty(), which compares working-tree vs index (always clean after
            # add -A) instead of index vs HEAD.
            # ------------------------------------------------------------------
            staged_files = repo.git.diff("--cached", "--name-only").strip()
            logger.debug("Rollback: staged files = %r", staged_files)

            if not staged_files:
                logger.info(
                    "Rollback: nothing to commit — working tree already matches %s",
                    target.hexsha[:8],
                )
                return target.hexsha

            author = Actor(GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL)
            target_title = target.message.strip().split("\n")[0]
            msg = (
                f"Rollback to {target.hexsha[:8]}\n\n"
                f"Restored state from commit {target.hexsha[:8]}\n"
                f"{target_title}"
            )
            c = repo.index.commit(msg, author=author, committer=author)
            logger.info(
                "Rollback complete: %s → %s (new commit %s)",
                head_sha[:8], target.hexsha[:8], c.hexsha[:8],
            )
            return c.hexsha

        except Exception as exc:
            logger.exception("Rollback failed (target=%s)", target.hexsha[:8])
            raise ValueError(f"Rollback failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Show a file at a given commit
    # ------------------------------------------------------------------

    def show_file_at(self, commit_sha: str, relative_path: str) -> str | None:
        """Return file contents at *commit_sha*, or ``None`` if absent."""
        repo = self.repo
        try:
            target = repo.commit(commit_sha)
            blob = target.tree / relative_path
            return blob.data_stream.read().decode("utf-8")
        except (KeyError, Exception):
            return None
