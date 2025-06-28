import asyncio
from bleak import BleakScanner, BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

# 蓝牙UUID常量
HRS_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

async def main():
    # 扫描设备
    print("正在扫描心率设备...")
    
    device_found = None
    
    def detection_callback(device, advertisement_data):
        nonlocal device_found
        if HRS_UUID in advertisement_data.service_uuids and device_found is None:
            device_found = device
            print(f"扫描到设备{device.name or '未知'} 已连接")
    
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    await asyncio.sleep(5)
    await scanner.stop()
    
    if not device_found:
        print("未找到心率设备")
        return
    
    # 连接设备
    try:
        client = BleakClient(device_found.address)
        await client.connect()
        
        # 获取心率服务
        services = list(client.services)
        heart_rate_service = None
        
        for service in services:
            if service.uuid.lower() == HRS_UUID.lower():
                heart_rate_service = service
                break
        
        if not heart_rate_service:
            print("未找到心率服务")
            return
        
        # 获取心率测量特征
        heart_rate_characteristic = None
        for char in heart_rate_service.characteristics:
            if char.uuid.lower() == HRM_UUID.lower():
                heart_rate_characteristic = char
                break
        
        if not heart_rate_characteristic:
            print("未找到心率测量特征")
            return
        
        # 心率数据处理函数
        def notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
            if len(data) >= 2:
                flag = data[0]
                heart_rate = data[1]
                
                if flag & 0b00001 != 0 and len(data) >= 3:
                    heart_rate |= (data[2] << 8)
                
                if 40 <= heart_rate <= 240:
                    print(heart_rate)  # 只输出数字
        
        # 订阅通知
        await client.start_notify(heart_rate_characteristic, notification_handler)
        
        # 保持连接
        while client.is_connected:
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"连接失败: {e}")
    finally:
        if client and client.is_connected:
            await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
    except Exception as e:
        print(f"程序出错: {e}") 