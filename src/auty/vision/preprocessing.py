"""Lighting normalization for the Auty vision pipeline.

Applies CLAHE to the L channel of the LAB color space so that recognition
works consistently under dim or uneven lighting conditions (e.g. a dim
warehouse entrance at 6 am).  The operation is applied to the full BGR frame
before any face detection so that both the detector and the embedder see a
contrast-normalized image.
"""

from __future__ import annotations

import cv2
import numpy as np


def normalize_lighting(bgr_frame: np.ndarray) -> np.ndarray:
    """Apply CLAHE to the L channel of LAB to correct uneven/dim lighting.

    Parameters
    ----------
    bgr_frame:
        A BGR image as returned by ``cv2.imdecode`` or a camera read.

    Returns
    -------
    np.ndarray
        A BGR image of identical shape and dtype with the L channel
        contrast-enhanced.  The input frame is not modified in place.
    """
    if bgr_frame is None or bgr_frame.size == 0:
        return bgr_frame

    lab = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)

    lab = cv2.merge((l_channel, a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
