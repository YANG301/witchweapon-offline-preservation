package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Catalog-backed administrator view and patch planner. Called under LocalSave's account monitor. */
final class AdminDataService {
    private static final long BALANCE_MAX=1000000000000L;
    private static final long COUNT_MAX=1000000000L;
    private AdminDataService() {}

    static final class ActiveBattle extends IOException {
        ActiveBattle(){super("Finish the active battle before editing or restoring");}
    }
    static boolean busy(JSONObject state){
        long round=state.optLong("mazeRound",1);
        return state.optBoolean("active",false) || (round>=1 && round<=12 &&
            state.optLong("mazePreparedRound",0)==round && !state.optBoolean("mazeRoundSettled",false));
    }
    static final class Plan {
        final JSONObject next;
        final JSONArray changes=new JSONArray();
        final Set<String> changedKeys=new LinkedHashSet<String>();
        boolean inventory,collection;
        Plan(JSONObject source)throws Exception{next=new JSONObject(source.toString());}
        JSONObject preview(long revision)throws Exception{
            return new JSONObject().put("revision",Long.toString(revision))
                .put("changes",changes).put("changeCount",changes.length());
        }
        void change(String key,String label,String before,String after)throws Exception{
            if(before.equals(after))return;
            changes.put(new JSONObject().put("key",key).put("label",label)
                .put("before",before).put("after",after));changedKeys.add(key);
        }
        void bumpSync()throws Exception{
            if(inventory)next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
            if(collection)next.put("collectionRevision",Math.addExact(next.optLong("collectionRevision",0),1));
        }
    }
    private static final class Field {
        final String key,label,group,type;final Object value;final long min,max;
        final JSONArray catalog;final String help;
        Field(String key,String label,String group,String type,Object value,long min,long max,
                JSONArray catalog,String help){
            this.key=key;this.label=label;this.group=group;this.type=type;this.value=value;
            this.min=min;this.max=max;this.catalog=catalog;this.help=help;
        }
        JSONObject json()throws Exception{
            JSONObject result=new JSONObject().put("key",key).put("label",label).put("group",group)
                .put("type",type).put("value",value).put("min",Long.toString(min))
                .put("max",Long.toString(max));
            if(catalog!=null)result.put("catalog",catalog);
            if(help!=null)result.put("help",help);
            return result;
        }
    }
    private static void scalar(Map<String,Field> out,JSONObject save,String key,String label,
            String group,long fallback,long max)throws Exception{
        out.put(key,new Field(key,label,group,"integer",Long.toString(save.optLong(key,fallback)),
            0,max,null,null));
    }
    private static List<String> keys(JSONObject source){
        List<String> keys=new ArrayList<String>();
        for(Iterator<String> it=source.keys();it.hasNext();)keys.add(it.next());
        Collections.sort(keys);return keys;
    }
    private static long itemCap(JSONObject catalog,String id)throws Exception{
        long cap=LocalEconomy.stackCap(catalog,id);
        // The game reserves 500 slots for this original item during clampBag.
        return "40330006".equals(id)?Math.max(0,cap-500):cap;
    }
    private static String resourceLabel(JSONObject definition,String id,boolean equip){
        String label=definition.optString("name","");
        if(label.isEmpty())label=definition.optString("label","");
        if(label.isEmpty())label=definition.optString(equip?"equip_name":"item_name","");
        if(label.matches("[0-9]+"))label=""; // A localization key is not a translated name.
        if(!label.isEmpty())return label+" ("+id+")";
        if(!equip){
            if("40310001".equals(id))return "魔女经验道具 ("+id+")";
            if("40330099".equals(id))return "体力道具 ("+id+")";
            if("40340010".equals(id))return "改名卡 ("+id+")";
            if("40350003".equals(id))return "塔罗券 ("+id+")";
        }
        return (equip?"装备 ":"道具 ")+id;
    }
    private static void bag(Map<String,Field> out,JSONObject save,JSONObject source,String kind)throws Exception{
        JSONObject definitions=source.optJSONObject(kind);if(definitions==null)return;
        JSONObject current=save.optJSONObject(kind),values=new JSONObject();JSONArray catalog=new JSONArray();
        for(String id:keys(definitions)){
            if(!id.matches("[1-9][0-9]{0,18}"))continue;
            JSONObject definition=definitions.getJSONObject(id);
            long cap=kind.equals("items")?itemCap(source,id):9999;
            catalog.put(new JSONObject().put("id",id)
                .put("label",resourceLabel(definition,id,kind.equals("equips")))
                .put("max",Long.toString(cap)));
            if(current!=null && current.has(id))values.put(id,Long.toString(current.getLong(id)));
        }
        String label=kind.equals("items")?"道具数量":"装备数量";
        out.put(kind,new Field(kind,label,kind.equals("items")?"道具":"装备","map",values,
            0,9999,catalog,"仅提交改变的 ID；数量 0 表示清空该资源，所有 ID 和堆叠上限由游戏目录校验。"));
    }
    private static void servantField(Map<String,Field> fields,String id,String suffix,String label,
            long value,long min,long max,String help){
        String key="servants."+id+"."+suffix;
        fields.put(key,new Field(key,"魔女 "+id+" · "+label,"魔女成长","integer",
            Long.toString(value),min,max,null,help));
    }
    private static Map<String,Field> fields(JSONObject save,JSONObject catalog,StageCatalog stages)throws Exception{
        Map<String,Field> out=new LinkedHashMap<String,Field>();
        if(save.optBoolean("roleCreated",false))out.put("name",new Field("name","角色昵称","基本信息",
            "text",save.getString("name"),2,16,null,"2–16 个字符，不允许首尾空白或控制字符。"));
        String[][] balances={{"gold","金币"},{"rmb","钻石"},{"guildCurrency","公会币"},
            {"cscCurrency","迷宫币"},{"drawCurrency","抽卡币"},{"recycleCurrency","回收币"},
            {"storyCurrency","剧情币"},{"activeCurrencyRed","红色活动币"},
            {"activeCurrencyYellow","黄色活动币"},{"activeCurrencyBlue","蓝色活动币"},
            {"activeCurrencyGreen","绿色活动币"},{"vipExp","C.A.P.H 积分"},{"vipPoint","C.A.P.H 兑换点"}};
        for(String[] entry:balances)scalar(out,save,entry[0],entry[1],"货币与资源",
            entry[0].equals("rmb")?100000:0,BALANCE_MAX);
        scalar(out,save,"exp","角色累计经验","体力与成长",0,BALANCE_MAX);
        scalar(out,save,"stamina","体力","体力与成长",200,1000000);
        scalar(out,save,"activityStamina","活动体力","体力与成长",200,1000000);
        if(save.optBoolean("roleCreated",false)){
            bag(out,save,catalog,"items");bag(out,save,catalog,"equips");
            JSONObject owned=save.optJSONObject("ownedServants"),templates=catalog.optJSONObject("servants");
            if(owned!=null && templates!=null)for(String id:keys(owned)){
                if(!templates.has(id))continue;
                ProtoWire servant=LocalEconomy.decode(owned.getString(id));
                if(servant.number(1,0)!=Long.parseLong(id))throw new IOException("Invalid servant identity");
                servantField(out,id,"level","等级",servant.number(2,1),1,65,"武器等级不得高于魔女等级；修改等级时同时调整经验和阶级。" );
                servantField(out,id,"exp","本级经验",servant.number(3,0),0,BALANCE_MAX,"未达 65 级时须小于当前等级的升级经验。" );
                servantField(out,id,"rank","阶级",servant.number(4,1),1,10,"对应阶级必须存在于目录，魔女等级须达到阶级要求。" );
                servantField(out,id,"star","星级",servant.number(5,1),0,5,null);
                servantField(out,id,"equipMask","装备槽位图",servant.number(7,0),0,63,"六个槽位的位图：0 为空，63 为全部装备。" );
                servantField(out,id,"weaponLevel","武器等级",servant.number(12,1),1,65,null);
                servantField(out,id,"weaponExp","武器本级经验",servant.number(16,0),0,BALANCE_MAX,null);
                long favorCap=catalog.getJSONObject("favorCaps").getLong(id);
                servantField(out,id,"favorLevel","好感等级",servant.number(9,1),1,favorCap,null);
                servantField(out,id,"favorExp","好感本级经验",servant.number(10,0),0,BALANCE_MAX,"未达好感等级上限时须小于 50；已领取的好感奖励记录保留。" );
                List<Long> skills=servant.integers(8);
                for(int i=0;i<5;i++)servantField(out,id,"skill"+(i+1),"技能 "+(i+1)+" 等级",
                    i<skills.size()?skills.get(i):1,1,100,null);
            }
            if(stages!=null)for(long chapter=3010001;chapter<=3010016;chapter++)
                for(long id:stages.stagesForChapter(chapter)){
                    JSONObject all=save.optJSONObject("mainlineStages");
                    JSONObject progress=all==null?null:all.optJSONObject(Long.toString(id));
                    if(progress==null){progress=new JSONObject();if(id==LocalSave.STAGE)
                        for(String key:new String[]{"wins","attempts","stars"})progress.put(key,save.optLong(key,0));}
                    for(String suffix:new String[]{"wins","attempts","stars"}){
                        String key="mainline."+id+"."+suffix;
                        String label=suffix.equals("wins")?"胜利次数":suffix.equals("attempts")?"挑战次数":"星数";
                        out.put(key,new Field(key,"关卡 "+id+" · "+label,"主线关卡进度","integer",
                            Long.toString(progress.optLong(suffix,0)),0,suffix.equals("stars")?3:COUNT_MAX,null,
                            "胜利次数不得超过挑战次数；首通奖励领取记录保留。"));
                    }
                }
            scalar(out,save,"mazeWins","迷宫胜利次数","迷宫进度",0,COUNT_MAX);
            scalar(out,save,"mazeAttempts","迷宫挑战次数","迷宫进度",0,COUNT_MAX);
            scalar(out,save,"mazeStars","迷宫星数","迷宫进度",0,3);
        }
        return out;
    }
    static Object strings(Object value)throws Exception{
        if(value instanceof JSONObject){JSONObject result=new JSONObject();JSONObject object=(JSONObject)value;
            for(String key:keys(object))result.put(key,strings(object.get(key)));return result;}
        if(value instanceof JSONArray){JSONArray result=new JSONArray(),array=(JSONArray)value;
            for(int i=0;i<array.length();i++)result.put(strings(array.get(i)));return result;}
        return value instanceof Number?value.toString():value;
    }
    static JSONObject view(JSONObject state,long revision,JSONObject catalog,StageCatalog stages)throws Exception{
        JSONArray editable=new JSONArray();for(Field field:fields(state,catalog,stages).values())editable.put(field.json());
        JSONObject readOnly=(JSONObject)strings(state);
        for(String key:new String[]{"name","gold","rmb","exp","stamina","activityStamina",
            "guildCurrency","cscCurrency","drawCurrency","recycleCurrency","storyCurrency",
            "activeCurrencyRed","activeCurrencyYellow","activeCurrencyBlue","activeCurrencyGreen","vipExp","vipPoint"})
            readOnly.remove(key);
        return new JSONObject().put("version",1).put("revision",Long.toString(revision))
            .put("fields",editable).put("readOnly",readOnly).put("active",busy(state));
    }
    static long number(String value,long min,long max)throws LocalSave.AdminValidation{
        if(value==null || !value.matches("(?:0|[1-9][0-9]{0,18})"))throw new LocalSave.AdminValidation("Invalid integer");
        try{long result=Long.parseLong(value);if(result>=min && result<=max)return result;}
        catch(NumberFormatException ignored){}
        throw new LocalSave.AdminValidation("Integer outside its catalog limits");
    }
    static boolean text(String value,int min,int max){
        if(value==null || value.codePointCount(0,value.length())<min || value.codePointCount(0,value.length())>max ||
            value.getBytes(StandardCharsets.UTF_8).length>512)return false;
        if(value.isEmpty())return false;
        int first=value.codePointAt(0),last=value.codePointBefore(value.length());
        if(Character.isWhitespace(first)||Character.isSpaceChar(first)||Character.isWhitespace(last)||Character.isSpaceChar(last))return false;
        for(int i=0;i<value.length();){int cp=value.codePointAt(i);
            if(Character.isISOControl(cp)||Character.getType(cp)==Character.FORMAT || (cp>=0xD800&&cp<=0xDFFF))return false;
            i+=Character.charCount(cp);}
        return true;
    }
    static long expected(Map<String,String> args,long revision,String... allowed)throws Exception{
        Set<String> names=new HashSet<String>(Arrays.asList(allowed));
        names.add("expectedRevision");names.add("reason");
        for(String key:args.keySet())if(!names.contains(key))throw new LocalSave.AdminValidation("Unknown admin field");
        if(!text(args.get("reason"),1,200))throw new LocalSave.AdminValidation("A valid reason is required");
        long expected=number(args.get("expectedRevision"),0,Long.MAX_VALUE);
        if(expected!=revision)throw new LocalSave.AdminConflict();return expected;
    }
    static Plan plan(JSONObject state,JSONObject catalog,StageCatalog stages,String raw)throws Exception{
        if(busy(state))throw new ActiveBattle();
        if(raw==null || raw.getBytes(StandardCharsets.UTF_8).length>262144)
            throw new LocalSave.AdminValidation("Missing or oversized changes");
        JSONObject input=new PatchJson(raw).parse();
        if(input.length()==0 || input.length()>128)throw new LocalSave.AdminValidation("Select 1 to 128 fields");
        return plan(state,catalog,stages,input,false);
    }
    private static Plan plan(JSONObject state,JSONObject catalog,StageCatalog stages,JSONObject input,boolean restoring)throws Exception{
        Map<String,Field> schema=fields(state,catalog,stages);Plan plan=new Plan(state);
        Set<String> servants=new HashSet<String>(),mainline=new HashSet<String>();
        for(String key:keys(input)){
            Field field=schema.get(key);if(field==null)throw new LocalSave.AdminValidation("Field is not editable: "+key);
            Object requested=input.get(key);
            if(field.type.equals("map")){
                if(!(requested instanceof JSONObject))throw new LocalSave.AdminValidation("Resource changes must be a map");
                JSONObject updates=(JSONObject)requested,bag=plan.next.optJSONObject(key);
                if(bag==null){bag=new JSONObject();plan.next.put(key,bag);}
                JSONObject values=(JSONObject)field.value,definitions=catalog.getJSONObject(key);
                if(updates.length()>2000)throw new LocalSave.AdminValidation("Too many resource entries");
                for(String id:keys(updates)){
                    if(!definitions.has(id) || !(updates.get(id) instanceof String))
                        throw new LocalSave.AdminValidation("Unknown resource ID or invalid quantity");
                    String before=values.optString(id,"0");
                    // Legacy saves may already exceed today's cap. A no-op must remain a no-op.
                    if(before.equals(updates.getString(id)))continue;
                    long cap=key.equals("items")?itemCap(catalog,id):9999;
                    long amount=number(updates.getString(id),0,cap);
                    String after=Long.toString(amount);
                    plan.change(key+"."+id,resourceLabel(definitions.getJSONObject(id),id,key.equals("equips")),before,after);
                    if(!before.equals(after)){bag.put(id,amount);plan.inventory=true;}
                }
            }else{
                if(!(requested instanceof String))throw new LocalSave.AdminValidation("Field values must be strings");
                String value=(String)requested;
                if(field.type.equals("text")){
                    if(!text(value,2,16)||value.getBytes(StandardCharsets.UTF_8).length>128)
                        throw new LocalSave.AdminValidation("Invalid role name");
                    if(!field.value.equals(value))plan.next.put(key,value);
                    plan.change(key,field.label,(String)field.value,value);
                }else{
                    long amount=number(value,field.min,field.max);String after=Long.toString(amount);
                    if(field.value.equals(after))continue;
                    plan.change(key,field.label,(String)field.value,after);
                    if(key.startsWith("servants.")){
                        String[] parts=key.split("\\.");String id=parts[1],suffix=parts[2];servants.add(id);
                        JSONObject owned=plan.next.getJSONObject("ownedServants");ProtoWire servant=LocalEconomy.decode(owned.getString(id));
                        if(suffix.startsWith("skill")){
                            List<Long> levels=servant.integers(8);while(levels.size()<5)levels.add(1L);
                            levels.set(Integer.parseInt(suffix.substring(5))-1,amount);servant.clear(8);
                            for(int i=0;i<5;i++)servant.add(8,levels.get(i));
                        }else servant.set(servantNumber(suffix),amount);
                        owned.put(id,LocalEconomy.encode(servant));plan.inventory=true;plan.collection=true;
                    }else if(key.startsWith("mainline.")){
                        String[] parts=key.split("\\.");String id=parts[1];mainline.add(id);
                        JSONObject all=plan.next.optJSONObject("mainlineStages");
                        if(all==null){all=new JSONObject();plan.next.put("mainlineStages",all);}
                        JSONObject progress=all.optJSONObject(id);
                        if(progress==null){progress=new JSONObject();all.put(id,progress);
                            if(Long.toString(LocalSave.STAGE).equals(id))for(String name:new String[]{"wins","attempts","stars"})
                                progress.put(name,state.optLong(name,0));}
                        progress.put(parts[2],amount);
                        if(Long.toString(LocalSave.STAGE).equals(id))plan.next.put(parts[2],amount);
                    }else plan.next.put(key,amount);
                }
            }
        }
        if(plan.changes.length()>(restoring?4096:2000))throw new LocalSave.AdminValidation("Too many changed entries");
        for(String id:servants)validateServant(plan.next,catalog,id);
        for(String id:mainline){JSONObject progress=plan.next.getJSONObject("mainlineStages").getJSONObject(id);
            validateProgress(progress,"wins","attempts","stars");
            // A progress rollback must not re-open an already granted first-clear reward.
            JSONObject allBefore=state.optJSONObject("mainlineStages");
            JSONObject before=allBefore==null?null:allBefore.optJSONObject(id);
            long winsBefore=before!=null?before.optLong("wins",0):
                Long.toString(LocalSave.STAGE).equals(id)?state.optLong("wins",0):0;
            if(progress.optLong("wins",0)>0 || winsBefore>0 || (before!=null && before.optBoolean("firstRewardClaimed",false)))
                progress.put("firstRewardClaimed",true);}
        if(input.has("mazeWins")||input.has("mazeAttempts")||input.has("mazeStars"))
            validateProgress(plan.next,"mazeWins","mazeAttempts","mazeStars");
        if(plan.changes.length()>0){
            if(input.has("exp")||input.has("stamina"))
                StaminaRecovery.reconcileMutation(plan.next,StaminaRecovery.level(plan.next,catalog),System.currentTimeMillis()/1000);
            plan.bumpSync();
        }
        return plan;
    }
    private static int servantNumber(String suffix)throws LocalSave.AdminValidation{
        String[] names={"level","exp","rank","star","equipMask","favorLevel","favorExp","weaponLevel","weaponExp"};
        int[] numbers={2,3,4,5,7,9,10,12,16};
        for(int i=0;i<names.length;i++)if(names[i].equals(suffix))return numbers[i];
        throw new LocalSave.AdminValidation("Unknown servant field");
    }
    private static void validateServant(JSONObject save,JSONObject catalog,String id)throws Exception{
        ProtoWire servant=LocalEconomy.decode(save.getJSONObject("ownedServants").getString(id));
        long level=servant.number(2,1),rank=servant.number(4,1),weapon=servant.number(12,1);
        JSONObject rankInfo=catalog.getJSONObject("ranks").getJSONObject(id).optJSONObject(Long.toString(rank));
        if(rankInfo==null || level<rankInfo.getLong("minLevel") || weapon>level)
            throw new LocalSave.AdminValidation("Servant level, rank and weapon level are inconsistent");
        long cost=catalog.getJSONObject("levels").optLong(Long.toString(level),0);
        long weaponCost=catalog.getJSONObject("weaponLevels").getJSONObject(id).optLong(Long.toString(weapon),0);
        if((level<65 && (cost<=0 || servant.number(3,0)>=cost)) ||
           (weapon<Math.min(65,level) && (weaponCost<=0 || servant.number(16,0)>=weaponCost)))
            throw new LocalSave.AdminValidation("Servant EXP exceeds its level threshold");
        long favorCap=catalog.getJSONObject("favorCaps").getLong(id);
        if(servant.number(9,1)<favorCap && servant.number(10,0)>=50)
            throw new LocalSave.AdminValidation("Favor EXP exceeds its level threshold");
    }
    private static void validateProgress(JSONObject progress,String wins,String attempts,String stars)throws Exception{
        if(progress.optLong(wins,0)>progress.optLong(attempts,0) ||
            (progress.optLong(stars,0)>0 && progress.optLong(wins,0)==0))
            throw new LocalSave.AdminValidation("Stage wins, attempts and stars are inconsistent");
    }
    static Plan restore(JSONObject current,JSONObject old,JSONObject catalog,StageCatalog stages)throws Exception{
        if(busy(current))throw new ActiveBattle();
        if(old.optInt("version",0)!=1 || old.optBoolean("roleCreated",false)!=current.optBoolean("roleCreated",false) ||
            old.optLong("legacyRoleId",0)!=current.optLong("legacyRoleId",0))
            throw new LocalSave.AdminValidation("Backup role identity does not match the current account");
        Map<String,Field> existing=fields(current,catalog,stages),past=fields(old,catalog,stages);
        JSONObject changes=new JSONObject();
        for(Field field:existing.values()){
            Field previous=past.get(field.key);if(previous==null)continue;
            if(field.type.equals("map")){
                JSONObject now=(JSONObject)field.value,before=(JSONObject)previous.value,updates=new JSONObject();
                Set<String> ids=new TreeSet<String>();ids.addAll(keys(now));ids.addAll(keys(before));
                for(String id:ids)updates.put(id,before.optString(id,"0"));
                if(updates.length()>0)changes.put(field.key,updates);
            }else if(!field.value.equals(previous.value))changes.put(field.key,previous.value);
        }
        return plan(current,catalog,stages,changes,true);
    }
    static JSONArray retainedFields(JSONObject current)throws Exception{
        JSONArray result=new JSONArray();
        for(String key:keys(current))if(!Arrays.asList("name","gold","rmb","exp","stamina","activityStamina",
            "guildCurrency","cscCurrency","drawCurrency","recycleCurrency","storyCurrency","activeCurrencyRed",
            "activeCurrencyYellow","activeCurrencyBlue","activeCurrencyGreen","vipExp","vipPoint","items","equips",
            "ownedServants","mainlineStages","wins","attempts","stars","mazeWins","mazeAttempts","mazeStars").contains(key))result.put(key);
        result.put("ownedServants.identityAndOtherWireFields");result.put("mainlineStages.firstRewardClaimed");return result;
    }

    /** Strict two-level JSON: duplicates, numeric precision loss and permissive JSON extensions are rejected. */
    private static final class PatchJson {
        private final String raw;private int offset;
        PatchJson(String raw){this.raw=raw;}
        JSONObject parse()throws Exception{JSONObject result=object(0);space();if(offset!=raw.length())bad();return result;}
        private void space(){while(offset<raw.length() && " \t\r\n".indexOf(raw.charAt(offset))>=0)offset++;}
        private void bad()throws LocalSave.AdminValidation{throw new LocalSave.AdminValidation("Changes must be strict JSON with string values");}
        private void take(char expected)throws LocalSave.AdminValidation{space();if(offset>=raw.length()||raw.charAt(offset++)!=expected)bad();}
        private JSONObject object(int depth)throws Exception{
            take('{');JSONObject result=new JSONObject();space();if(offset<raw.length()&&raw.charAt(offset)=='}'){offset++;return result;}
            while(true){String key=string();if(result.has(key))bad();take(':');space();
                Object value;
                if(offset<raw.length()&&raw.charAt(offset)=='{'&&depth==0)value=object(depth+1);else value=string();
                result.put(key,value);space();if(offset>=raw.length())bad();char end=raw.charAt(offset++);
                if(end=='}')return result;if(end!=',')bad();}
        }
        private String string()throws Exception{
            take('"');StringBuilder result=new StringBuilder();
            while(offset<raw.length()){
                char c=raw.charAt(offset++);if(c=='"')return result.toString();if(c<32)bad();
                if(c!='\\'){result.append(c);continue;}if(offset>=raw.length())bad();c=raw.charAt(offset++);
                switch(c){case '"':case '\\':case '/':result.append(c);break;
                    case 'b':result.append('\b');break;case 'f':result.append('\f');break;
                    case 'n':result.append('\n');break;case 'r':result.append('\r');break;case 't':result.append('\t');break;
                    case 'u':if(offset+4>raw.length())bad();int number=0;
                        for(int i=0;i<4;i++){int hex=Character.digit(raw.charAt(offset++),16);if(hex<0)bad();number=(number<<4)|hex;}
                        result.append((char)number);break;default:bad();}
            }
            bad();return "";
        }
    }
}
