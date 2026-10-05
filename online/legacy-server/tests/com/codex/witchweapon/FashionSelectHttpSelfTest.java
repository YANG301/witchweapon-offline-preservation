package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import com.sun.net.httpserver.HttpServer;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** Real loopback route, proxy authentication, ownership and save atomicity. */
public final class FashionSelectHttpSelfTest {
    private static final String SECRET="test-secret-0123456789-0123456789-0123456789";
    private static final String ALICE="aaaaaaaaaaaaaaaaaaaaaa";
    private static final String BOB="bbbbbbbbbbbbbbbbbbbbbb";
    private static final byte[] OK=new ProtoWire().text(1,"ok").bytes();
    private static void check(boolean value,String reason){
        if(!value)throw new AssertionError(reason);
    }
    private static JSONObject read(Path path)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(path),StandardCharsets.UTF_8));
    }
    private static byte[] fixture(JSONObject responses,String path)throws Exception{
        return Base64.decode(responses.getJSONObject(path).getString("base64"),Base64.DEFAULT);
    }
    private static Path createAccount(Path root,String id,JSONObject responses,
                                      JSONObject catalog)throws Exception{
        Path dir=root.resolve("users").resolve(id);
        Files.createDirectories(dir);
        LocalSave save=new LocalSave(dir.toFile());
        Map<String,String> form=new HashMap<String,String>();form.put("name",id);
        save.respond("/role/create",form,fixture(responses,"/role/create"),catalog);
        return dir.resolve("offline_save_v1.json");
    }
    private static final class Response {
        final int status;final byte[] body;
        Response(int status,byte[] body){this.status=status;this.body=body;}
    }
    private static Response request(int port,String path,String method,String account,
                                    boolean authenticated,String contentType,String body)
            throws Exception{
        HttpURLConnection connection=(HttpURLConnection)new URL(
            "http://127.0.0.1:"+port+path).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(3000);connection.setReadTimeout(3000);
        connection.setRequestProperty("X-WW-Account-ID",account);
        if(authenticated)connection.setRequestProperty("X-WW-Proxy-Secret",SECRET);
        if(body!=null){
            byte[] bytes=body.getBytes(StandardCharsets.UTF_8);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type",contentType);
            connection.setFixedLengthStreamingMode(bytes.length);
            connection.getOutputStream().write(bytes);
        }
        int status=connection.getResponseCode();
        InputStream stream=status>=400?connection.getErrorStream():connection.getInputStream();
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        if(stream!=null)try(InputStream in=stream){
            byte[] buffer=new byte[1024];int n;
            while((n=in.read(buffer))>=0)out.write(buffer,0,n);
        }
        connection.disconnect();
        return new Response(status,out.toByteArray());
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException(
            "Arguments: offline_responses.json isolated_test_root");
        Path root=Paths.get(args[1]).toAbsolutePath().normalize();
        if(Files.exists(root))throw new IllegalArgumentException("Test root must not exist");
        Files.createDirectories(root);
        JSONObject responses=read(Paths.get(args[0])),catalog=responses.getJSONObject("_catalog");
        Path aliceSave=createAccount(root,ALICE,responses,catalog);
        Path bobSave=createAccount(root,BOB,responses,catalog);
        JSONObject alice=read(aliceSave);
        alice.put("fashionOwned",new JSONObject().put("70000002",true));
        Files.write(aliceSave,(alice.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));

        HttpServer server=HttpServer.create(new InetSocketAddress(
            InetAddress.getByName("127.0.0.1"),0),8);
        int port=server.getAddress().getPort();
        Constructor<StandaloneServer> constructor=StandaloneServer.class.getDeclaredConstructor(
            Path.class,Path.class,int.class,String.class);
        constructor.setAccessible(true);
        StandaloneServer host=constructor.newInstance(Paths.get(args[0]),root,port,SECRET);
        final Method handle=StandaloneServer.class.getDeclaredMethod("handle",
            com.sun.net.httpserver.HttpExchange.class);
        handle.setAccessible(true);
        server.createContext("/",exchange->{
            try{handle.invoke(host,exchange);}catch(Exception ex){
                throw new java.io.IOException("Test host failed",ex);
            }
        });
        server.start();
        try{
            Response result=request(port,"/fashion/select","POST",ALICE,false,
                "application/x-www-form-urlencoded","fashioncardid=70000002");
            check(result.status==403,"Route accepted a request without proxy authentication");
            result=request(port,"/fashion/select","GET",ALICE,true,null,null);
            check(result.status==405,"Route accepted GET");
            result=request(port,"/fashion/select","POST",ALICE,true,"text/plain","fashioncardid=70000002");
            check(result.status==415,"Route accepted non-form content");
            result=request(port,"/fashion/select","POST","cccccccccccccccccccccc",true,
                "application/x-www-form-urlencoded","fashioncardid=70000002");
            check(result.status==404,"Route created an unknown account save");
            result=request(port,"/fashion/select","POST",BOB,true,
                "application/x-www-form-urlencoded","fashioncardid=70000002");
            check(result.status==422,"Account B selected account A's locked outfit");
            check(!read(bobSave).has("curFashion"),"Rejected selection changed account B");
            result=request(port,"/fashion/select","POST",ALICE,true,
                "application/x-www-form-urlencoded","fashioncardid=70000002");
            check(result.status==200 && Arrays.equals(result.body,OK),
                "Owned selection did not return the original CommonInfo shape");
            JSONObject saved=read(aliceSave);
            check(saved.getLong("curFashion")==70000002L,
                "Selection did not enter account A's save");
            long revision=saved.getLong("saveRevision");
            result=request(port,"/game/fashion/select","POST",ALICE,true,
                "application/x-www-form-urlencoded","fashioncardid=70000002");
            check(result.status==200 && read(aliceSave).getLong("saveRevision")==revision,
                "Repeated selection should be idempotent");
            result=request(port,"/fashion/select","POST",ALICE,true,
                "application/x-www-form-urlencoded","fashioncardid=0");
            check(result.status==422 && read(aliceSave).getLong("curFashion")==70000002L,
                "Invalid selection changed account A");
        }finally{server.stop(0);}
        System.out.println("FASHION_SELECT_HTTP_SELF_TEST_OK");
    }
}
