import subprocess
import datetime
from pathlib import Path
from .utils import setup_logger

logger = setup_logger()

class Publisher:
    def __init__(self, dummy_arg=None):
        # Dynamically targets the sibling repository: ~/flucidOS/flucidOS-src-meta
        self.sources_repo = Path(__file__).resolve().parent.parent.parent / "flucidOS-src-meta"

    def push(self):
        if not (self.sources_repo / ".git").exists():
            logger.error(f"The directory '{self.sources_repo}' is not initialized as a git repository.")
            return

        print("\n" + "="*40)
        print("➡ Push FlucidOS Sources to Remote")
        print("="*40)
        
        try:
            commit_msg = input("Enter the commit message: ").strip()
        except KeyboardInterrupt:
            print("\nPush cancelled by user.")
            return

        if not commit_msg:
            logger.error("Commit message cannot be empty. Aborting.")
            return

        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        full_message = f"{commit_msg} - {date_str}"

        try:
            logger.info(f"Staging all changes in {self.sources_repo}...")
            subprocess.run(["git", "add", "-A"], cwd=self.sources_repo, check=True)

            status = subprocess.run(["git", "status", "--porcelain"], cwd=self.sources_repo, capture_output=True, text=True)
            if not status.stdout.strip():
                logger.info("No changes to commit. Everything is already up to date.")
                return

            logger.info(f"Committing with message: '{full_message}'")
            subprocess.run(["git", "commit", "-m", full_message], cwd=self.sources_repo, check=True)

            logger.info("Pushing to remote repository...")
            subprocess.run(["git", "push"], cwd=self.sources_repo, check=True)
            
            logger.info("\n✔ Successfully pushed source code to remote!")

        except subprocess.CalledProcessError as e:
            logger.error(f"Git operation failed: {e}")
