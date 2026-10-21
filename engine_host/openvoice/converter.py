# Copyright © 2026 Infinite Story LLP. All rights reserved. (OpenVoice model code: MIT, MyShell.ai)
"""Tone-colour conversion: keep the words, rhythm, pitch movement and emotion of a performance, swap the
voice timbre for a target speaker. Used for (a) giving any expressive engine your own voice, and
(b) "Perform it yourself" — record a line and hear it in another voice."""
from __future__ import annotations

import numpy as np
import torch

from .hparams import get_hparams_from_file
from .mel_processing import spectrogram_torch
from .models import SynthesizerTrn


class ToneColorConverter:
    def __init__(self, config_path: str, ckpt_path: str, device: str = "cpu"):
        hps = get_hparams_from_file(config_path)
        self.hps, self.device = hps, device
        self.model = SynthesizerTrn(len(getattr(hps, "symbols", [])), hps.data.filter_length // 2 + 1,
                                    n_speakers=hps.data.n_speakers, **hps.model).to(device)
        self.model.eval()
        ck = torch.load(ckpt_path, map_location=torch.device(device))
        self.model.load_state_dict(ck["model"], strict=False)

    @property
    def sr(self) -> int:
        return int(self.hps.data.sampling_rate)

    def _spec(self, audio: np.ndarray):
        h = self.hps.data
        y = torch.FloatTensor(np.asarray(audio, dtype=np.float32)).to(self.device).unsqueeze(0)
        return spectrogram_torch(y, h.filter_length, h.sampling_rate, h.hop_length, h.win_length, center=False)

    @torch.no_grad()
    def embedding(self, clips: list[np.ndarray]) -> torch.Tensor:
        """Speaker tone-colour embedding from one or more clips at self.sr (averaged)."""
        gs = []
        for a in clips:
            spec = self._spec(a)
            gs.append(self.model.ref_enc(spec.transpose(1, 2)).unsqueeze(-1))
        return torch.stack(gs).mean(0)

    @torch.no_grad()
    def convert(self, audio: np.ndarray, src_se: torch.Tensor, tgt_se: torch.Tensor, tau: float = 0.3) -> np.ndarray:
        spec = self._spec(audio)
        lengths = torch.LongTensor([spec.size(-1)]).to(self.device)
        out = self.model.voice_conversion(spec, lengths, sid_src=src_se, sid_tgt=tgt_se, tau=tau)[0][0, 0]
        return out.detach().cpu().float().numpy()
