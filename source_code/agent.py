import json
import shutil
import warnings
from pathlib import Path
from dotenv import load_dotenv

warnings.filterwarnings(
    "ignore",
    message=".*Pydantic V1 functionality isn't compatible with Python 3.14.*",
    category=UserWarning
)

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

load_dotenv()


def validate_downloads_path(downloads_path: Path) -> None:
    """Validates that the path is the user's Downloads directory."""
    downloads_dir = downloads_path.resolve()
    home_dir = Path.home().resolve()
    
    if not downloads_dir.exists():
        raise ValueError(f"Downloads directory does not exist: {downloads_path}")
    if not downloads_dir.is_dir():
        raise ValueError(f"Path is not a directory: {downloads_path}")
    if downloads_dir.name != "Downloads":
        raise ValueError(f"Path must be the Downloads directory. Got: {downloads_path}")
    if downloads_dir.parent != home_dir:
        raise ValueError(f"Downloads directory must be directly under user's home directory (~/Downloads). Got: {downloads_dir}")


class CleanupSummary(BaseModel):
    """Structured output schema for cleanup operation summary."""
    files_moved: list[str] = Field(description="List of filenames that were moved")
    total_count: int = Field(description="Total number of files moved")
    action_taken: str = Field(description="Action taken: 'deleted' or 'kept'")
    target_folder: str = Field(description="Path to the Old Schoolwork folder")


def list_pdf_files(downloads_dir: Path) -> list[str]:
    """Lists all PDF files in the Downloads directory."""
    return [
        f.name for f in downloads_dir.iterdir()
        if f.is_file() and f.suffix.lower() == '.pdf'
    ]


class FilenameClassification(BaseModel):
    """Structured output for filename classification."""
    school_related_files: list[str] = Field(description="List of unique filenames that are school-related")


def classify_filenames(filenames: list[str]) -> list[str]:
    """Uses LLM to identify which filenames are school-related."""
    if not filenames:
        return []
    
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
    
    # Use structured output for reliable parsing
    structured_model = model.with_structured_output(FilenameClassification)
    
    prompt = f"""Analyze these PDF filenames and identify which ones appear to be school-related assignments.

Filenames: {json.dumps(filenames, indent=2)}

School-related indicators include: Essay, Homework, Lecture, Exam, Assignment, Project, Notes, Study, Quiz, Test, Report, Paper, etc.

CRITICAL REQUIREMENTS:
1. Return ONLY filenames from the list above. Do NOT generate, create, or invent new filenames.
2. Only return exact matches from the provided list.
3. Each filename should appear ONLY ONCE in your response - no duplicates.
4. Be conservative - if unsure, don't include it."""

    try:
        result = structured_model.invoke(prompt)
        valid_filenames = list(dict.fromkeys([f for f in result.school_related_files if f in filenames]))
        invalid_count = len(result.school_related_files) - len(valid_filenames)
        if invalid_count > 0:
            print(f"Warning: LLM returned {invalid_count} invalid filename(s) that weren't in the original list")
        return valid_filenames
    except Exception as e:
        print(f"Warning: Error classifying filenames: {e}")
        return []


def edit_file_list(filenames: list[str]) -> list[str] | None:
    """Allows user to remove files from the list before moving.
    
    Returns:
        list[str]: Edited list of filenames
    None: If user wants to stop execution (entered "STOP")
    """
    if not filenames:
        return []
    
    print("\n" + "=" * 60)
    print("Files to move:")
    print("=" * 60)
    for i, filename in enumerate(filenames, 1):
        print(f"  {i}. {filename}")
    
    response = input(
        """
Want to save any files from being deleted? (Note: These files will NOT be deleted.)

- To save files, enter their numbers separated by commas. Those files will NOT be deleted.
- To delete all files, simply press Enter.
- Type 'STOP' + Enter to cancel.
"""
    ).strip()
    
    if not response:
        return filenames
    
    if response.upper() == "STOP":
        print("\nStopping execution. No files will be moved.")
        return None
    
    try:
        numbers = [int(x.strip()) for x in response.replace(',', ' ').split() if x.strip()]
        indices_to_remove = {n - 1 for n in numbers if 1 <= n <= len(filenames)}
        
        if not indices_to_remove:
            print("No valid numbers entered. Keeping all files.")
            return filenames
        
        remaining = [f for i, f in enumerate(filenames) if i not in indices_to_remove]
        print(f"\nRemoved {len(filenames) - len(remaining)} file(s). {len(remaining)} file(s) will be moved.")
        return remaining
    except ValueError:
        print("Invalid input. Keeping all files.")
        return filenames


def ensure_target_folder(target_folder: Path) -> None:
    """Creates the Old Schoolwork folder if it doesn't exist."""
    target_folder.mkdir(parents=True, exist_ok=True)


def get_unique_target_path(source_file: Path, target_folder: Path) -> Path:
    """Returns a unique target path, handling duplicates by appending numbers."""
    target_file = target_folder / source_file.name
    if not target_file.exists():
        return target_file
    
    base_name, extension = source_file.stem, source_file.suffix
    counter = 1
    while target_file.exists():
        target_file = target_folder / f"{base_name}_{counter}{extension}"
        counter += 1
    return target_file


def move_files(filenames: list[str], downloads_dir: Path, target_folder: Path) -> dict:
    """Moves files from Downloads to Old Schoolwork folder."""
    moved_files = []
    errors = []
    
    for filename in filenames:
        if '/' in filename or '\\' in filename:
            errors.append(f"{filename}: Filename cannot contain path separators")
            continue
        
        source_file = downloads_dir / filename
        if not source_file.exists() or not source_file.is_file():
            errors.append(f"{filename}: File not found")
            continue
        
        target_file = get_unique_target_path(source_file, target_folder)
        
        try:
            shutil.move(str(source_file), str(target_file))
            moved_files.append(filename)
        except PermissionError:
            errors.append(f"{filename}: Permission denied")
        except Exception as e:
            errors.append(f"{filename}: {e}")
    
    return {
        "moved_count": len(moved_files),
        "moved_files": moved_files,
        "errors": errors
    }


def main():
    """Main execution flow."""
    downloads_path = Path.home() / "Downloads"
    
    print("=" * 60)
    print("HomeworkHeap")
    print("=" * 60)
    print(f"Working with Downloads directory: {downloads_path}\n")
    
    try:
        validate_downloads_path(downloads_path)
    except ValueError as e:
        print(f"Error: {e}")
        return
    
    downloads_dir = downloads_path.resolve()
    target_folder = downloads_dir / "Old Schoolwork"
    
    # Step 1: List PDF files
    print("Scanning for PDF files...")
    pdf_files = list_pdf_files(downloads_dir)
    print(f"Found {len(pdf_files)} PDF file(s)\n")
    
    if not pdf_files:
        print("No PDF files found. Nothing to organize.")
        return
    
    # Step 2: Classify filenames with LLM
    print("Classifying filenames (using LLM)...")
    school_files = classify_filenames(pdf_files)
    
    if not school_files:
        print("No school-related files found. Nothing to move.")
        return
    
    print(f"Identified {len(school_files)} school-related file(s)\n")
    
    # Step 3: Allow user to edit the list
    school_files = edit_file_list(school_files)
    
    if school_files is None:
        # User entered "STOP" - exit completely
        return
    
    if not school_files:
        print("No files selected. Nothing to move.")
        return
    
    # Step 4: Ensure target folder exists
    ensure_target_folder(target_folder)
    print()
    
    # Step 5: Move files
    print("Moving files...")
    result = move_files(school_files, downloads_dir, target_folder)
    
    if result["moved_count"] > 0:
        print(f"Successfully moved {result['moved_count']} file(s)")
    else:
        print("No files were moved")
    
    if result["errors"]:
        print(f"\nErrors ({len(result['errors'])}):")
        for error in result["errors"]:
            print(f"  - {error}")
    print()
    
    # Step 6: Ask for user approval
    print("=" * 60)
    user_approval = input("Do you want to delete the 'Old Schoolwork' folder? (yes/no): ").strip().lower()
    print()
    
    if user_approval in ["yes", "y"]:
        try:
            if target_folder.exists():
                shutil.rmtree(target_folder)
                print("Successfully deleted folder: Old Schoolwork\n")
            else:
                print("Folder 'Old Schoolwork' does not exist\n")
            action_taken = "deleted"
        except Exception as e:
            print(f"Error deleting folder: {e}\n")
            action_taken = "kept"
    else:
        print("Keeping the 'Old Schoolwork' folder.\n")
        action_taken = "kept"
    
    # Generate summary
    summary = CleanupSummary(
        files_moved=result["moved_files"],
        total_count=result["moved_count"],
        action_taken=action_taken,
        target_folder=str(target_folder)
    )
    
    print("=" * 60)
    print("Cleanup Summary:")
    print("=" * 60)
    print(json.dumps(summary.model_dump(), indent=2))


if __name__ == "__main__":
    main()
