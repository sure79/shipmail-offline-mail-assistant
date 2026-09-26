@echo off
setlocal
set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_NO_CLOUD=1
set OLLAMA_DEBUG=0
set OLLAMA_MAX_LOADED_MODELS=1
set OLLAMA_NUM_PARALLEL=1
rem Memory savers for 4GB VRAM (measured: 3.56GB -> 3.04GB, more layers on GPU)
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_KV_CACHE_TYPE=q8_0
echo Close any existing Ollama tray app before starting this local-only server.
echo No model downloads will be performed by this script.
where ollama >nul 2>nul
if not errorlevel 1 (
  ollama serve
) else (
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
  ) else (
    echo Ollama is not installed. See README.md for approved installation steps.
  )
)
pause
