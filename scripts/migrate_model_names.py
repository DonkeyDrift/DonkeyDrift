
import os
import re
import secrets
import string
import shutil
import argparse
from datetime import datetime

def generate_random_suffix():
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(4))

def migrate_models(models_dir, dry_run=False):
    if not os.path.exists(models_dir):
        print(f"Directory {models_dir} not found.")
        return

    folder_name = os.path.basename(os.path.abspath(os.path.join(models_dir, "..")))
    print(f"Project Folder Name: {folder_name}")
    print(f"Scanning {models_dir}...\n")

    # Old format regex: {base}-{date}-{seq}.tflite
    # e.g. pilot-231027-001.tflite
    # We want to capture base and date
    old_pattern = re.compile(r"^(.+)-(\d{6})-(\d{3})\.tflite$")
    
    # New format regex: {folder}-{base}-{date}-{RAND}.tflite
    # To avoid double migration
    new_pattern = re.compile(rf"^{re.escape(folder_name)}-.+-\d{{6}}-[A-Z0-9]{{4}}\.tflite$")

    migrated_count = 0
    skipped_count = 0

    for filename in os.listdir(models_dir):
        if not filename.endswith(".tflite"):
            continue

        file_path = os.path.join(models_dir, filename)
        
        # Check if already in new format
        if new_pattern.match(filename):
            print(f"[SKIP] Already new format: {filename}")
            skipped_count += 1
            continue

        match = old_pattern.match(filename)
        if match:
            base_name = match.group(1)
            date_str = match.group(2)
            # seq = match.group(3) # We discard sequence and generate random suffix

            # Clean base name just in case
            clean_base = re.sub(r'[^a-zA-Z0-9_]', '', base_name)
            if not clean_base:
                clean_base = "model"

            # Generate new unique name
            while True:
                suffix = generate_random_suffix()
                new_filename = f"{folder_name}-{clean_base}-{date_str}-{suffix}.tflite"
                new_path = os.path.join(models_dir, new_filename)
                
                if not os.path.exists(new_path):
                    break
            
            if dry_run:
                print(f"[DRY-RUN] Would rename: {filename} -> {new_filename}")
            else:
                try:
                    shutil.move(file_path, new_path)
                    print(f"[OK] Renamed: {filename} -> {new_filename}")
                except Exception as e:
                    print(f"[ERR] Failed to rename {filename}: {e}")
            
            migrated_count += 1
        else:
            print(f"[SKIP] Unrecognized format: {filename}")
            skipped_count += 1

    print(f"\nMigration Summary:")
    print(f"  Processed: {migrated_count}")
    print(f"  Skipped:   {skipped_count}")
    if dry_run:
        print("  (Dry run mode - no changes applied)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate model filenames to new naming convention.")
    parser.add_argument("--dir", default="./models", help="Path to models directory (default: ./models)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without renaming files")
    
    args = parser.parse_args()
    
    migrate_models(args.dir, args.dry_run)
