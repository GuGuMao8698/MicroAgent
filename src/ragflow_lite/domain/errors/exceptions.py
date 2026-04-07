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
