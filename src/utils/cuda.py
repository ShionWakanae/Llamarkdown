import sys
from rich import print

try:
    import torch
except ImportError:
    print("[red]PyTorch is not installed.[/red]")
    print("Please install dependencies first:\npip install -r requirements.txt")
    sys.exit(1)


def check_cuda(settings) -> None:
    """
    Validate PyTorch CUDA environment against current settings.
    """

    torch_cuda_available = torch.cuda.is_available()
    embedding_device = str(settings.embedding_device).lower()

    # Case 1:
    # CUDA available, but user still uses CPU
    if torch_cuda_available and embedding_device == "cpu":
        gpu_name = torch.cuda.get_device_name(0)

        print(
            f"[yellow]CUDA is available ({gpu_name}), torch version {torch.version.cuda}, "
            f"but EMBEDDING_DEVICE=cpu.[/yellow]"
        )

        print(
            "[yellow]You can change EMBEDDING_DEVICE to 'cuda' "
            "for significantly faster embedding performance.[/yellow]"
        )

        return

    # Case 2:
    # User configured CUDA, but CUDA unavailable
    if not torch_cuda_available and embedding_device == "cuda":
        print("[red]CUDA is not available in the current PyTorch environment.[/red]")

        print(
            "\nChoose one of the following:\n"
            "1. Change EMBEDDING_DEVICE=cpu (slower)\n"
            "2. Install the CUDA version of PyTorch\n"
        )

        print(
            "Example:\n"
            "pip uninstall torch torchvision torchaudio\n"
            "pip install torch torchvision torchaudio "
            "--index-url https://download.pytorch.org/whl/cu128"
        )

        sys.exit(1)
