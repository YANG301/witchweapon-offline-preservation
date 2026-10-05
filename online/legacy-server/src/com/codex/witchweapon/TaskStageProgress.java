package com.codex.witchweapon;

import org.json.JSONObject;

/** Read exact-stage clears from the existing authoritative battle ledgers. */
final class TaskStageProgress {
    private TaskStageProgress(){}

    static long wins(JSONObject state,long stage){
        String id=Long.toString(stage);
        long completed=0;
        for(String field:new String[]{"mainlineStages","dailyBattleStages","furnaceStages"}){
            JSONObject stages=state.optJSONObject(field);
            JSONObject record=stages==null?null:stages.optJSONObject(id);
            // Migrated clears may appear in two ledgers. Do not add them or
            // count a different difficulty, failed attempt or mere unlock.
            if(record!=null)completed=Math.max(completed,record.optLong("wins",0));
        }
        return completed;
    }
}
