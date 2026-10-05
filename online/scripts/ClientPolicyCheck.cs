using System;
using WitchWeapon.Online;

// 独立校验客户端的实际协议策略源码；不能替代 Unity 编辑器编译和画面验证。
internal static class ClientPolicyCheck
{
    private static void CheckUrl(string value, bool expected)
    {
        string normalized, error;
        bool actual = ClientPolicy.TryBaseUrl(value, out normalized, out error);
        if (actual != expected) throw new Exception("URL policy failed: " + value);
    }

    private static int Main()
    {
        CheckUrl("http://127.0.0.1:18080", true);
        CheckUrl("http://localhost:18080/", true);
        CheckUrl("http://[::1]:18080", true);
        CheckUrl("https://game.example.test", true);
        CheckUrl("http://game.example.test", false);
        CheckUrl("http://localhost.example.test", false);
        CheckUrl("http://127.0.0.1.example.test", false);
        CheckUrl("https://user:password@game.example.test", false);
        CheckUrl("https://game.example.test?token=value", false);
        CheckUrl("https://game.example.test#token", false);
        CheckUrl("file:///C:/test", false);
        CheckUrl("ftp://localhost", false);
        if (ClientPolicy.PasswordCharacters("你好世界12345678") != 12) throw new Exception("CJK password count");
        if (ClientPolicy.PasswordCharacters("\U0001F64212345678901") != 12) throw new Exception("Unicode password count");
        if (ClientPolicy.PasswordCharacters(" ") != 1) throw new Exception("Password space was removed");
        if (ClientPolicy.PasswordCharacters("\uD800") != -1) throw new Exception("Malformed Unicode was accepted");
        Console.WriteLine("PASS: actual C# client URL policy and Unicode password rules.");
        return 0;
    }
}
