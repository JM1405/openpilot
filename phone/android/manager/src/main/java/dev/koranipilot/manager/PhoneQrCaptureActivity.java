package dev.koranipilot.manager;

import android.os.Bundle;
import android.view.WindowManager;
import com.journeyapps.barcodescanner.CaptureActivity;

/** Camera frames stay in the local decoder; no barcode image is saved. */
public final class PhoneQrCaptureActivity extends CaptureActivity {
  @Override public void onCreate(Bundle state) {
    getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
    super.onCreate(state);
  }
}
