package dev.koranipilot.manager;

/** Shareable diagnostics: exception messages may contain keys, URLs or locations. */
final class KakaoStartupFailure {
  enum Stage {
    INSTALL("I1 SDK 설치"), INITIALIZE("I2 SDK 초기화"), GUIDANCE("G1 안내 객체"),
    VIEW("G2 지도 화면 생성"), DELEGATES("G3 안내 연결"),
    LIFECYCLE("G4 화면 활성화"), START("G5 무목적지 시작"), CLEANUP("G6 안내 종료");
    final String label;
    Stage(String label){this.label=label;}
  }

  static String describe(Stage stage,Throwable error){
    StringBuilder out=new StringBuilder(stage.label);
    for(int depth=0;error!=null&&depth<3;depth++,error=error.getCause()){
      out.append(depth==0?" · ":" ← ").append(error.getClass().getSimpleName());
      for(StackTraceElement frame:error.getStackTrace()){
        String name=frame.getClassName();
        if(name.startsWith("com.kakaomobility.knsdk.")||name.startsWith("dev.koranipilot.manager.")){
          out.append(" @ ").append(name.substring(name.lastIndexOf('.')+1))
            .append(':').append(frame.getLineNumber());break;
        }
      }
    }
    return out.toString();
  }
}
