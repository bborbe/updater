"""File handling utilities."""


def condense_file_list(files: list[str]) -> list[str]:
    """Condense file list by grouping vendor files.

    Args:
        files: List of file paths

    Returns:
        Condensed list where vendor/* files are grouped as "vendor/** (N files)"
    """
    vendor_files = [f for f in files if f.startswith("vendor/")]
    non_vendor_files = [f for f in files if not f.startswith("vendor/")]

    result = non_vendor_files.copy()

    if vendor_files:
        result.append(f"vendor/** ({len(vendor_files)} files)")

    return result
