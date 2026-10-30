"""Optional hard-stop process boundary for blocking provider HTTP requests.

Thread cancellation cannot terminate an in-flight requests call. Here, each
request runs in a spawn-isolated child process, whose lifetime is bounded by
the parent. This is an availability control, NOT a sandbox for untrusted code.
"""
from __future__ import annotations
import multiprocessing as mp
from typing import Any
from router_errors import CandidateError

def _provider_worker(connection, provider: str, model: str, prompt: str,
                     system_text: str | None, timeout: float, max_tokens: int):
    try:
        from model_router import RAW_CAPTURE, Candidate, Router
        captured = []
        token = RAW_CAPTURE.set(captured)
        try:
            answer = Router(timeout=timeout).generate(
                Candidate(provider, model), prompt, probe=False,
                request_timeout=max(.5,timeout-.5),
                max_output_tokens=max_tokens, system_text=system_text)
            output = {"ok":True,"answer":answer,
                      "raw":captured[-1] if captured else None}
        finally:
            RAW_CAPTURE.reset(token)
    except CandidateError as error:
        output = {"ok":False,"kind":error.kind}
    except Exception:
        # Never echo exception/URL/credentials across the process boundary.
        output = {"ok":False,"kind":"provider_worker_error"}
    try:
        connection.send(output)
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        connection.close()

def generate(provider: str, model: str, prompt: str, *,
             system_text: str | None, timeout: float,
             max_tokens: int = 1800) -> tuple[str, dict | None]:
    if not 0 < timeout <= 120 or not 1 <= max_tokens <= 8192:
        raise ValueError("Invalid bounded process request")
    ctx = mp.get_context("spawn")
    receiving, sending = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_provider_worker,
                        args=(sending,provider,model,prompt,system_text,
                              timeout,max_tokens),daemon=True)
    try:
        child.start()
        sending.close()
        if not receiving.poll(timeout):
            raise CandidateError("Hard inference deadline reached",kind="timeout")
        try:
            payload: dict[str,Any] = receiving.recv()
        except EOFError:
            raise CandidateError("Inference worker exited",kind="server") from None
        if not payload.get("ok"):
            raise CandidateError("Inference worker failed",
                                 kind=payload.get("kind","server"))
        return payload["answer"], payload.get("raw")
    finally:
        receiving.close()
        if child.pid is not None:
            if child.is_alive():
                child.terminate()
                child.join(timeout=1)
            if child.is_alive():
                child.kill()
            child.join(timeout=1)
        sending.close()
