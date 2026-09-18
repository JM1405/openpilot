package dev.koranipilot.manager;

import org.junit.Test;
import static org.junit.Assert.*;

/** Compilation alone does not catch dependencies used only inside the SDK UI. */
public class KakaoRuntimeDependenciesTest {
  @Test public void viewBindingRuntimeIsPresent() throws Exception {
    assertTrue(Class.forName("androidx.viewbinding.ViewBinding").isInterface());
    Class.forName("androidx.viewbinding.ViewBindings");
  }

  @Test public void pinnedSdkNaviBindingCanBeLinked() throws Exception {
    // ViewNaviBinding in pinned knsdk_ui 1.12.8-hotfix03; never used by product code.
    Class<?> binding=Class.forName("com.kakaomobility.knsdk.a0.f0",false,getClass().getClassLoader());
    assertTrue(Class.forName("androidx.viewbinding.ViewBinding").isAssignableFrom(binding));
  }
}
