"""Git manager — auto-managed git repository inside the state directory."""

import logging
from pathlib import Path

from git import Actor, InvalidGitRepositoryError, Repo

from config import GIT_AUTHOR_EMAIL, GIT_AUTHOR_NAME, STATE_DIR

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
        except (InvalidGitRepositoryError, Exception):
            self._repo = Repo.init(self._dir)
            # Perform an initial commit so HEAD exists
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
        """Return recent commits as a list of dicts."""
        repo = self.repo
        commits = []
        for c in repo.iter_commits(max_count=max_count):
            commits.append(
                {
                    "sha": c.hexsha,
                    "short_sha": c.hexsha[:8],
                    "message": c.message.strip(),
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
        repo = self.repo
        try:
            target = repo.commit(commit_sha)
        except Exception as exc:
            raise ValueError(f"Cannot resolve commit '{commit_sha}': {exc}") from exc

        # Checkout the tree of the target commit onto the index
        repo.git.checkout(target.hexsha, "--", ".")

        # Stage everything (picks up restored files *and* removals)
        repo.git.add(A=True)

        if not repo.is_dirty(index=True, untracked_files=True):
            # Already identical — nothing to commit
            return target.hexsha

        author = Actor(GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL)
        msg = f"Rollback to {target.hexsha[:8]}"
        c = repo.index.commit(msg, author=author, committer=author)
        logger.info("Rolled back to %s (%s)", target.hexsha[:8], c.hexsha[:8])
        return c.hexsha

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
