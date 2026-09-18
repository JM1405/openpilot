package dev.koranipilot.manager;

/** Explicit SDK meanings only. Unknown codes are omitted, never guessed by substring. */
final class TurnHint {
  static String label(String code){
    if(code==null)return "";
    switch(code){
      case "KNRGCode_LeftTurn":return "좌회전";
      case "KNRGCode_UnprotectedLeftTurn":return "비보호 좌회전";
      case "KNRGCode_RightTurn":return "우회전";
      case "KNRGCode_UTurn":return "유턴";
      case "KNRGCode_Straight":return "직진";
      case "KNRGCode_LeftDirection":return "왼쪽 방향";
      case "KNRGCode_RightDirection":return "오른쪽 방향";
      case "KNRGCode_LeftOutHighway":case "KNRGCode_LeftOutCityway":return "왼쪽 진출";
      case "KNRGCode_RightOutHighway":case "KNRGCode_RightOutCityway":return "오른쪽 진출";
      case "KNRGCode_OutHighway":case "KNRGCode_OutCityway":return "진출";
      case "KNRGCode_LeftInHighway":case "KNRGCode_LeftInCityway":return "왼쪽 진입";
      case "KNRGCode_RightInHighway":case "KNRGCode_RightInCityway":return "오른쪽 진입";
      case "KNRGCode_InHighway":case "KNRGCode_InCityway":return "진입";
      case "KNRGCode_Goal":return "목적지";
      default:return "";
    }
  }
}
