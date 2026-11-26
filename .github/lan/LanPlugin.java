package com.nyxvault.lastcampfire;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.Closeable;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

@CapacitorPlugin(name = "Lan")
public class LanPlugin extends Plugin {
    private static final int PORT = 45678;
    private static final int CONNECT_TIMEOUT_MS = 12000;
    private static final int WIFI_WAIT_MS = 12000;
    private static final int MAX_FRAME_CHARS = 262144;

    private final Object lock = new Object();
    private final Object writeLock = new Object();
    private final ExecutorService io = Executors.newCachedThreadPool();

    private volatile ConnectivityManager connectivityManager;
    private volatile ServerSocket serverSocket;
    private volatile Socket peerSocket;
    private volatile BufferedWriter writer;
    private volatile boolean hosting = false;
    private volatile boolean connecting = false;
    private volatile boolean connected = false;

    @Override
    public void load() {
        connectivityManager = (ConnectivityManager) getContext()
            .getSystemService(Context.CONNECTIVITY_SERVICE);
    }

    private void status(String message) {
        JSObject event = new JSObject();
        event.put("message", message);
        notifyListeners("status", event);
    }

    private static int wifiInterfaceScore(String name) {
        String n = name == null ? "" : name.toLowerCase();
        if (n.equals("ap0")) return 100;
        if (n.startsWith("swlan")) return 95;
        if (n.equals("wlan0")) return 90;
        if (n.startsWith("wlan")) return 85;
        if (n.startsWith("wifi")) return 70;
        if (n.startsWith("p2p")) return 20;
        if (n.startsWith("rmnet") || n.startsWith("ccmni")
            || n.startsWith("pdp") || n.startsWith("tun")
            || n.startsWith("lo") || n.startsWith("dummy")) return -1;
        return 1;
    }

    private String localIpv4() {
        try {
            Enumeration<NetworkInterface> enumeration = NetworkInterface.getNetworkInterfaces();
            if (enumeration == null) return "";
            List<NetworkInterface> interfaces = Collections.list(enumeration);
            interfaces.sort((a, b) ->
                Integer.compare(wifiInterfaceScore(b.getName()), wifiInterfaceScore(a.getName()))
            );

            for (NetworkInterface ni : interfaces) {
                if (wifiInterfaceScore(ni.getName()) < 0 || !ni.isUp() || ni.isLoopback()) continue;
                Enumeration<InetAddress> addresses = ni.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress address = addresses.nextElement();
                    if (address instanceof Inet4Address
                        && !address.isLoopbackAddress()
                        && !address.isLinkLocalAddress()
                        && address.isSiteLocalAddress()) {
                        return address.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return "";
    }

    @PluginMethod
    public void host(PluginCall call) {
        synchronized (lock) {
            if (hosting || serverSocket != null) {
                call.reject("Комната уже запускается или создана");
                return;
            }
            if (connecting || connected) {
                call.reject("Сначала остановите текущее LAN-соединение");
                return;
            }
            hosting = true;
        }

        io.execute(() -> {
            ServerSocket listener = null;
            Socket accepted = null;
            boolean callResolved = false;
            try {
                listener = new ServerSocket();
                listener.setReuseAddress(true);
                listener.bind(new InetSocketAddress(PORT));

                synchronized (lock) {
                    if (!hosting) throw new IOException("Запуск комнаты отменён");
                    serverSocket = listener;
                }

                String ip = localIpv4();
                JSObject result = new JSObject();
                result.put("ok", true);
                result.put("ip", ip);
                result.put("port", PORT);
                call.resolve(result);
                callResolved = true;

                status("Комната создана. IP хоста: "
                    + (ip.isEmpty() ? "не удалось определить — проверьте Wi-Fi" : ip)
                    + ", порт " + PORT + ". Ожидание игрока.");

                accepted = listener.accept();
                accepted.setTcpNoDelay(true);

                synchronized (lock) {
                    if (!hosting) throw new IOException("Комната остановлена");
                    peerSocket = accepted;
                    connected = true;
                }

                setWriter(accepted);
                status("Второй телефон подключился.");
                readLoop(accepted);
            } catch (Exception e) {
                if (!callResolved) {
                    call.reject("Не удалось создать комнату: " + safeMessage(e));
                } else if (hosting) {
                    status("Ошибка сервера: " + safeMessage(e));
                }
            } finally {
                synchronized (lock) {
                    hosting = false;
                    connected = false;
                    if (serverSocket == listener) serverSocket = null;
                    if (peerSocket == accepted) peerSocket = null;
                    writer = null;
                }
                closeQuietly(accepted);
                closeQuietly(listener);
                status("Сервер остановлен.");
            }
        });
    }

    private Network findWifiNetwork() throws Exception {
        ConnectivityManager cm = connectivityManager;
        if (cm == null) throw new IOException("Сетевой сервис Android недоступен");

        Network active = cm.getActiveNetwork();
        if (active != null) {
            NetworkCapabilities caps = cm.getNetworkCapabilities(active);
            if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                return active;
            }
        }

        final CountDownLatch latch = new CountDownLatch(1);
        final Network[] found = new Network[1];
        final ConnectivityManager.NetworkCallback callback =
            new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    found[0] = network;
                    latch.countDown();
                }

                @Override
                public void onUnavailable() {
                    latch.countDown();
                }
            };

        NetworkRequest request = new NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .build();

        boolean registered = false;
        try {
            cm.requestNetwork(request, callback);
            registered = true;
            boolean arrived = latch.await(WIFI_WAIT_MS, TimeUnit.MILLISECONDS);
            if (!arrived || found[0] == null) {
                throw new IOException("Wi-Fi-сеть не найдена. Подключите телефон к точке доступа хоста.");
            }
            return found[0];
        } finally {
            if (registered) {
                try {
                    cm.unregisterNetworkCallback(callback);
                } catch (Exception ignored) {
                }
            }
        }
    }

    private static boolean isValidIpv4(String value) {
        if (value == null) return false;
        String[] parts = value.trim().split("\\.", -1);
        if (parts.length != 4) return false;
        for (String part : parts) {
            if (part.isEmpty() || part.length() > 3) return false;
            for (int i = 0; i < part.length(); i++) {
                if (part.charAt(i) < '0' || part.charAt(i) > '9') return false;
            }
            try {
                int number = Integer.parseInt(part);
                if (number < 0 || number > 255) return false;
            } catch (NumberFormatException e) {
                return false;
            }
        }
        return true;
    }

    @PluginMethod
    public void connect(PluginCall call) {
        String ip = call.getString("ip");
        if (!isValidIpv4(ip)) {
            call.reject("Введите корректный IPv4-адрес телефона-хоста");
            return;
        }
        final String targetIp = ip.trim();

        synchronized (lock) {
            if (connected || connecting || hosting) {
                call.reject("LAN уже подключён или выполняется другое подключение");
                return;
            }
            connecting = true;
        }

        io.execute(() -> {
            Socket candidate = null;
            boolean callResolved = false;
            try {
                status("Подключаемся через Wi-Fi...");
                Network network = findWifiNetwork();

                candidate = new Socket();
                synchronized (lock) {
                    if (!connecting) throw new IOException("Подключение отменено");
                    peerSocket = candidate;
                }

                network.bindSocket(candidate);
                candidate.setTcpNoDelay(true);
                candidate.connect(
                    new InetSocketAddress(targetIp, PORT),
                    CONNECT_TIMEOUT_MS
                );

                setWriter(candidate);
                synchronized (lock) {
                    if (!connecting) throw new IOException("Подключение отменено");
                    connecting = false;
                    connected = true;
                }

                JSObject result = new JSObject();
                result.put("ok", true);
                result.put("ip", targetIp);
                result.put("port", PORT);
                call.resolve(result);
                callResolved = true;

                status("Подключено к " + targetIp + ". Канал связи готов.");
                readLoop(candidate);
            } catch (Exception e) {
                if (!callResolved) {
                    call.reject("Подключение не удалось: " + safeMessage(e));
                }
                if (connecting || connected) {
                    status("Связь не установлена: " + safeMessage(e));
                }
            } finally {
                synchronized (lock) {
                    connecting = false;
                    connected = false;
                    if (peerSocket == candidate) peerSocket = null;
                    writer = null;
                }
                closeQuietly(candidate);
            }
        });
    }

    private void setWriter(Socket socket) throws IOException {
        BufferedWriter next = new BufferedWriter(
            new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8)
        );
        synchronized (writeLock) {
            writer = next;
        }
    }

    private static String readBoundedLine(BufferedReader reader) throws IOException {
        StringBuilder frame = new StringBuilder(4096);
        int ch;
        while ((ch = reader.read()) != -1) {
            if (ch == '\n') break;
            if (ch != '\r') {
                if (frame.length() >= MAX_FRAME_CHARS) {
                    throw new IOException("Сетевой пакет слишком большой");
                }
                frame.append((char) ch);
            }
        }
        if (ch == -1 && frame.length() == 0) return null;
        return frame.toString();
    }

    private void readLoop(Socket socket) {
        try {
            BufferedReader reader = new BufferedReader(
                new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8)
            );
            String line;
            while ((line = readBoundedLine(reader)) != null) {
                JSObject event = new JSObject();
                event.put("data", line);
                notifyListeners("message", event);
            }
            status("Второй телефон отключился.");
        } catch (Exception e) {
            if (connected || hosting) {
                status("Соединение прервано: " + safeMessage(e));
            }
        }
    }

    @PluginMethod
    public void send(PluginCall call) {
        String data = call.getString("data", "ping");
        if (data == null || data.length() > MAX_FRAME_CHARS
            || data.indexOf('\n') >= 0 || data.indexOf('\r') >= 0) {
            call.reject("Сообщение пустое, слишком длинное или содержит перенос строки");
            return;
        }

        BufferedWriter current = writer;
        if (current == null || !connected) {
            call.reject("Нет подключённого игрока");
            return;
        }

        try {
            synchronized (writeLock) {
                current.write(data);
                current.newLine();
                current.flush();
            }
            call.resolve();
        } catch (IOException e) {
            call.reject("Ошибка отправки: " + safeMessage(e));
        }
    }

    @PluginMethod
    public void stop(PluginCall call) {
        ServerSocket server;
        Socket peer;
        synchronized (lock) {
            hosting = false;
            connecting = false;
            connected = false;
            server = serverSocket;
            peer = peerSocket;
            serverSocket = null;
            peerSocket = null;
            writer = null;
        }
        closeQuietly(peer);
        closeQuietly(server);
        call.resolve();
        status("LAN остановлен.");
    }

    private static String safeMessage(Exception e) {
        String message = e.getMessage();
        return message == null || message.trim().isEmpty()
            ? e.getClass().getSimpleName()
            : e.getClass().getSimpleName() + ": " + message;
    }

    private static void closeQuietly(Closeable closeable) {
        try {
            if (closeable != null) closeable.close();
        } catch (Exception ignored) {
        }
    }
}
