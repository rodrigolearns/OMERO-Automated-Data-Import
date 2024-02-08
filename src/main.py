# main.py

import sys
import json
from pathlib import Path
import time
from utils.logger import setup_logger
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ProcessPoolExecutor
import signal
from threading import Event

#Modules
from utils.config import load_settings, load_json
from utils.data_mover import DataPackageMover
# from utils.stager import DataPackageStager
# from utils.importer import DataPackageImporter

# Setup Configuration
CONFIG_PATH = sys.argv[1] if len(sys.argv) > 1 else "config/settings.yml" # Configuration
config = load_settings(CONFIG_PATH) # Load YAML configuration
DIRECTORY_STRUCTURE_PATH = config['directory_structure_file_path'] # Load JSON directory_structure
directory_structure = load_json(DIRECTORY_STRUCTURE_PATH)
executor = ProcessPoolExecutor(max_workers=config['max_workers']) # ProcessPoolExecutor with 4 workers
logger = setup_logger(__name__, config['log_file_path']) # Set up logging using setup_logger instead of basicConfig

class DataPackage:
    def __init__(self, landing_dir_base_path, group, user, project):
        self.group = group
        self.user = user
        self.project = project
        self.original_path = Path(landing_dir_base_path) / group / user / project
        self.hidden_path = None
        self.datasets = {}

def ingest(data_package, config):
    """
    """
    try:
        # Step 1: Move Data Package
        mover = DataPackageMover(data_package, config)
        move_result = mover.move_data_package()  # Adjust to capture the boolean return

        if not move_result:
            logger.error(f"Failed to move data package for project {data_package.project}. Check logs for details.")
            return 
        # Proceed with further processing only if the data package was successfully moved
        logger.info(f"Data package {data_package.project} moved successfully.")
        
        # # Step 2: Categorize Datasets
        # stager = DataPackageStager(config)  # Instantiate the DatasetStager class
        # data_package.datasets = stager.identify_datasets(data_package)  # Use the identify_datasets method


        # # Step 3: Import Data Package
        # importer = DataPackageImporter(config)
        # importer.import_data_package(data_package) 

        logger.info(f"Data package {data_package.project} processed successfully.")
    except Exception as e:
        logger.error(f"Error during ingestion for group: {data_package.group}, user: {data_package.user}, project: {data_package.project}: {e}")

# Handler class
class DataPackageHandler(FileSystemEventHandler):
    """
    Event handler class for the watchdog observer. 
    It checks for directory creation events and triggers the ingest function when a new directory is created.
    """
    def __init__(self, base_directory, group_folders, executor):
        self.base_directory = Path(base_directory)
        self.group_folders = group_folders
        self.executor = executor

    def on_created(self, event):
        try:
            created_dir = Path(event.src_path)
            if not event.is_directory:
                created_dir = created_dir.parent

            for group, users in self.group_folders.items():
                for user in users:
                    user_folder = self.base_directory / group / user
                    if created_dir.parent == user_folder:
                        logger.info(f"DataPackage detected: {config['landing_dir_base_path']}, {group}, {user}, {created_dir.name}")
                        data_package = DataPackage(config['landing_dir_base_path'], group, user, created_dir.name)
                        future = self.executor.submit(ingest, data_package, config)
                        future.add_done_callback(self.log_future_exception)
        except Exception as e:
            logger.error(f"Error during on_created event handling: {e}")

    def log_future_exception(self, future):
        """
        Callback function to log exceptions from futures.
        """
        try:
            future.result()  # This will raise any exceptions caught during the execution of the task
        except Exception as e:
            logger.error(f"Error in background task: {e}")

def main(directory):
    # Initialize the shutdown event
    shutdown_event = Event()

    def graceful_exit(signum, frame):
        """
        Signal handler for graceful shutdown.
        Sets the shutdown event to signal the main loop to exit.
        """
        logger.info("Graceful shutdown initiated.")
        shutdown_event.set()

    # Load JSON directory_structure
    with open(DIRECTORY_STRUCTURE_PATH, 'r') as f:
        directory_structure = json.load(f)
    group_folders = {group: users['membersOf'] for group, users in directory_structure['Groups'].items()}

    # Set up the observer
    observer = Observer()
    for group in group_folders.keys():
        event_handler = DataPackageHandler(directory, group_folders, executor)
        group_path = Path(directory) / group
        observer.schedule(event_handler, path=str(group_path), recursive=True)
    observer.start()

    logger.info("Starting the folder monitoring service.")

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    try:
        # Main loop waits for the shutdown event
        while not shutdown_event.is_set():
            time.sleep(1)
    finally:
        # Cleanup operations
        logger.info("Stopping the folder monitoring service.")
        observer.stop()
        observer.join()
        executor.shutdown(wait=True)
        logger.info("Folder monitoring service stopped.")

if __name__ == "__main__":
    if len(sys.argv) > 3:
        print("Usage: python main.py [config_file] [directory]")
        sys.exit(1)

    main(sys.argv[2])