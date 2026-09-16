package dev.supportpilot.device;

public class DeviceAccessDeniedException extends RuntimeException {
    public DeviceAccessDeniedException() { super("设备不存在或当前用户无权访问"); }
}
