package dev.koranipilot.manager;

import dev.comma.companion.PhoneClient;

/** Shareable diagnostics. Never include an exception message, URL, credential or payload. */
final class KakaoTransferFailure {
  enum Stage {
    CHALLENGE("K1", "카카오 요청"), FRAME("K2", "자료 준비"), SEND("K3", "카카오 전송"),
    RECEIPT("K4", "카카오 응답 확인"), ROUTE("R1", "경로 전송/응답");
    final String code,label;
    Stage(String code,String label){this.code=code;this.label=label;}
  }
  static String code(Stage stage,Throwable error){
    StringBuilder out=new StringBuilder(stage.code);
    for(int depth=0;error!=null&&depth<3;depth++,error=error.getCause()){
      if(error instanceof PhoneClient.TransportException){
        PhoneClient.TransportException transport=(PhoneClient.TransportException)error;
        return out.append(' ').append(transport.phase).append('/').append(transport.reason).toString();
      }
      if(error instanceof PhoneClient.ApiException){
        PhoneClient.ApiException api=(PhoneClient.ApiException)error;
        return out.append(" HTTP ").append(api.status).append('/').append(safeCode(api.code)).toString();
      }
      if(depth==0)out.append(' ').append(error.getClass().getSimpleName());
    }
    return out.toString();
  }
  static String detail(Stage stage,Throwable error){
    String reason=error instanceof PhoneClient.ApiException?safeReason(error.getMessage()):"";
    return stage.label+" · "+code(stage,error)+(reason.isEmpty()?"":"\n"+reason);
  }
  static String summary(Stage stage,Throwable error,String confirmedKakao,boolean connected){
    if(!connected)return "C4 연결 만료 · "+code(stage,error);
    if(stage==Stage.ROUTE&&confirmedKakao!=null)return confirmedKakao+" · 경로 확인 실패 · "+code(stage,error);
    return "C4 수신 확인 실패 · "+code(stage,error);
  }
  private static String safeCode(String code){
    if(code==null)return "unknown";
    switch(code){
      case "invalid":case "host":case "origin":case "csrf":case "stale":case "sequence":case "revision":
      case "unauthorized":case "receive_only":case "closed":case "blocked":case "home_unavailable":
      case "unavailable":case "missing":case "storage":return code;
      default:return "unknown";
    }
  }
  private static String safeReason(String message){
    if(message==null)return "";
    // Exact static server messages only; unknown or extended text stays private.
    switch(message){
      case "카카오 자료 형식을 확인해":case "카카오 수신 요청이 만료됐어":case "지난 카카오 자료야":
      case "카카오 안내 모드를 확인해":case "카카오 상태를 확인해":case "카카오 자료 시각을 확인해":
      case "카카오 속도 범위를 확인해":case "무목적지 GPS를 경로 매칭으로 처리할 수 없어":
      case "안전 안내 개수를 확인해":case "안전 안내 항목을 확인해":case "안전 안내 식별자를 확인해":
      case "안내 거리의 근거를 확인해":case "같은 경로의 거리가 아니야":case "확인되지 않은 거리를 사용할 수 없어":
      case "급커브/방지턱에 임의 속도를 넣을 수 없어":case "경로 자료 형식을 확인해":
      case "경로 수신 요청이 만료됐어":case "지난 경로 자료야":case "지난 경로 버전이야":
      case "경로 상태를 확인해":case "경로 위치·형상을 확인해":case "경로 거리·시각을 확인해":
      case "경로 좌표 개수를 확인해":case "경로 식별자를 확인해":case "회전 안내를 확인해":
      case "경로가 변경되면 버전을 올려줘":case "연결을 다시 확인한 뒤 요청해":
      case "같은 연결에서 요청해":case "올바른 요청 본문이 아니야":return message;
      default:return "";
    }
  }
}
