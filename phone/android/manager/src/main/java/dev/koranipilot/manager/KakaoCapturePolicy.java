package dev.koranipilot.manager;

/** Map/status capture is allowed only after the credential UI has been cleared. */
final class KakaoCapturePolicy {
  static boolean mustProtectKey(boolean authenticated,boolean keyVisible,boolean hasKeyText){
    return !authenticated||keyVisible||hasKeyText;
  }
}
