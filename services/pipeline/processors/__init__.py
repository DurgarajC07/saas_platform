"""
Processors package for the Pipeline Service.

Each module exports a single FrameProcessor subclass:

  stt.py       WhisperSTTProcessor   AudioRawFrame  → TranscriptionFrame
  tts.py       KokoroTTSProcessor    TextFrame      → AudioRawFrame
  llm.py       OllamaLLMProcessor    LLMMessagesFrame → TextFrame (streaming)
  vad.py       SileroVADProcessor    AudioRawFrame  → segmented AudioRawFrame
  noise.py     DeepFilterNetProcessor AudioRawFrame → denoised AudioRawFrame
  interrupt.py InterruptionHandler   detects barge-in, flushes TTS buffer
  rag.py       RAGRetrievalProcessor TranscriptionFrame → augmented LLMMessagesFrame
  tools.py     ToolExecutorProcessor FunctionCallFrame → FunctionResultFrame
"""
