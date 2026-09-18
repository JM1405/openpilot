"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.common.params import Params
from openpilot.sunnypilot.models.default_model import DEFAULT_MODEL


class ModelStateBase:
  def __init__(self):
    self.lat_delay = Params().get("LagdValueCache", return_default=True)
    self.model_ref, self.model_name, self.model_identity_known = "", DEFAULT_MODEL, True
    self.model_signature = "default"

  def report_model_identity(self, message):
    """Called only after this loaded model has produced an inference output."""
    message.valid = True
    message.modelDataV2SP.modelSignature = self.model_signature
    message.modelDataV2SP.modelRef = self.model_ref
    message.modelDataV2SP.modelName = self.model_name
    message.modelDataV2SP.modelIdentityKnown = self.model_identity_known
