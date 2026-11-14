package dev.koranipilot.manager;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import android.util.Base64;
import java.security.MessageDigest;

final class KeyHashUtil {
  private KeyHashUtil() {}

  @SuppressWarnings("deprecation")
  static String getSha1KeyHash(Context context) {
    try {
      PackageManager pm = context.getPackageManager();
      String pkg = context.getPackageName();
      Signature[] signatures = null;
      if (Build.VERSION.SDK_INT >= 28) {
        PackageInfo info = pm.getPackageInfo(pkg, PackageManager.GET_SIGNING_CERTIFICATES);
        if (info.signingInfo != null) {
          signatures = info.signingInfo.hasMultipleSigners()
              ? info.signingInfo.getApkContentsSigners()
              : info.signingInfo.getSigningCertificateHistory();
        }
      } else {
        PackageInfo info = pm.getPackageInfo(pkg, PackageManager.GET_SIGNATURES);
        signatures = info.signatures;
      }
      if (signatures == null || signatures.length == 0) {
        return "";
      }
      MessageDigest md = MessageDigest.getInstance("SHA-1");
      byte[] digest = md.digest(signatures[0].toByteArray());
      return Base64.encodeToString(digest, Base64.NO_WRAP);
    } catch (Exception ignored) {
      return "";
    }
  }

  static void copyToClipboard(Context context, String label, String value) {
    ClipboardManager cm = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
    if (cm != null) {
      cm.setPrimaryClip(ClipData.newPlainText(label, value == null ? "" : value));
    }
  }
}
