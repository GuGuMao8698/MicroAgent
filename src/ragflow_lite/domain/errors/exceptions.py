class RagflowLiteError(Exception):
    """Base exception for controlled application errors."""


class UnsupportedFileTypeError(RagflowLiteError):
    def __init__(self, filename: str) -> None:
        super().__init__(f"Unsupported file type for '{filename}'.")


class EmptyDocumentError(RagflowLiteError):
    def __init__(self, filename: str) -> None:
        super().__init__(f"Document '{filename}' does not contain usable text.")


class DocumentParsingError(RagflowLiteError):
    def __init__(self, filename: str) -> None:
        super().__init__(f"Failed to parse document '{filename}'.")


class IndexWriteError(RagflowLiteError):
    def __init__(self, document_id: str) -> None:
        super().__init__(f"Failed to persist index data for '{document_id}'.")


class ProcessingError(RagflowLiteError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class DocumentNotFoundError(RagflowLiteError):
    def __init__(self, document_id: str) -> None:
        super().__init__(f"Document '{document_id}' not found.")


class DatasetNotFoundError(RagflowLiteError):
    def __init__(self, dataset_id: str) -> None:
        super().__init__(f"Dataset '{dataset_id}' not found.")


class DatasetAlreadyExistsError(RagflowLiteError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Dataset with name '{name}' already exists.")


class DatasetNotEmptyError(RagflowLiteError):
    def __init__(self, dataset_id: str) -> None:
        super().__init__(
            f"Dataset '{dataset_id}' is not empty. Remove all documents first."
        )


class IdempotencyKeyMissingError(RagflowLiteError):
    def __init__(self) -> None:
        super().__init__("Idempotency-Key header is required.")
