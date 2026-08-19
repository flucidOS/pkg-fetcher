import subprocess
import datetime
from pathlib import Path
from .utils import setup_logger

logger = setup_logger()

class Publisher:
    def __init__(self, source_dir: str):
        self.sources = Path(source_dir)

    def push(self):
        # 1. Verify the sources directory is a Git repository
        if not (self.sources / ".git").exists():
            logger.error(f"The directory '{self.sources}' is not initialized as a git repository.")
            logger.info("Please initialize it and set up your remote branch first.")
            return

        print("\n" + "="*40)
        print("Push Sources to Remote")
        print("="*40)
        
        # 2. Prompt for the commit message
        try:
            commit_msg = input("Enter the commit message: ").strip()
        except KeyboardInterrupt:
            print("\nPush cancelled by administrator.")
            return

        if not commit_msg:
            logger.error("Commit message cannot be empty. Aborting.")
            return

        # 3. Format the message with the current date
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        full_message = f"{commit_msg} - {date_str}"

        try:
            # 4. Stage all changes
            logger.info(f"Staging all changes in {self.sources}...")
            subprocess.run(["git", "add", "-A"], cwd=self.sources, check=True)

            # 5. Check if there are actual changes to commit
            status = subprocess.run(
                ["git", "status", "--porcelain"], 
                cwd=self.sources, 
                capture_output=True, 
                text=True
            )
            
            if not status.stdout.strip():
                logger.info("No changes to commit. Everything is already up to date.")
                return

            # 6. Commit the changes
            logger.info(f"Committing with message: '{full_message}'")
            subprocess.run(["git", "commit", "-m", full_message], cwd=self.sources, check=True)

            # 7. Push to remote
            logger.info("Pushing to remote repository...")
            subprocess.run(["git", "push"], cwd=self.sources, check=True)
            
            logger.info("\n ✔ Successfully pushed all sources to remote!")

        except subprocess.CalledProcessError as e:
            logger.error(f"Git operation failed: {e}")
