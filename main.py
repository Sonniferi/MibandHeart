import asyncio
import csv
from datetime import datetime
from typing import Optional, Dict, Any, List
from bleak import BleakScanner, BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.scanner import AdvertisementData

# 蓝牙UUID常量
HRS_UUID = "0000180d-0000-1000-8000-00805f9b34fb"  # 心率服务UUID
HRM_UUID = "00002a37-0000-1000-8000-00805f9b34fb"  # 心率测量特征UUID

class HeartRateMonitor:
    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.device = None
        self.heart_rate_history = []
        self.is_connected = False
        self.csv_filename = None
        self.csv_writer = None
        self.csv_file = None
        
    def init_csv_file(self):
        """初始化CSV文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_filename = f"heart_rate_{timestamp}.csv"
        self.csv_file = open(self.csv_filename, 'w', newline='', encoding='utf-8')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(['time', 'rate'])
        print(f"数据将保存到: {self.csv_filename}")
        
    def parse_heart_rate_data(self, data: bytes) -> Dict[str, Any]:
        """解析心率数据，参考Rust代码的解析逻辑"""
        if len(data) < 2:
            return {"error": "数据长度不足"}
            
        flag = data[0]
        heart_rate_value = data[1]
        
        # 心率值格式判断
        if flag & 0b00001 != 0:
            # 16位心率值
            if len(data) >= 3:
                heart_rate_value |= (data[2] << 8)
        
        # 传感器接触状态
        sensor_contact = None
        if flag & 0b00100 != 0:
            sensor_contact = bool(flag & 0b00010)
            
        return {
            "heart_rate": heart_rate_value,
            "sensor_contact": sensor_contact,
            "flag": flag,
            "timestamp": datetime.now().isoformat()
        }
    
    def save_heart_rate_data(self, data: Dict[str, Any]):
        """保存心率数据到内存和CSV文件"""
        self.heart_rate_history.append(data)
        
        # 保存到CSV文件
        if self.csv_writer:
            time_str = datetime.now().strftime("%H:%M:%S")
            self.csv_writer.writerow([time_str, data['heart_rate']])
            self.csv_file.flush()  # 立即写入文件
        
        # 限制历史记录数量
        if len(self.heart_rate_history) > 1000:
            self.heart_rate_history = self.heart_rate_history[-500:]
    
    def close_csv_file(self):
        """关闭CSV文件"""
        if self.csv_file:
            self.csv_file.close()
            print(f"数据已保存到: {self.csv_filename}")

async def scan_for_heart_rate_devices() -> List:
    """扫描支持心率服务的设备，去重"""
    print("正在扫描心率设备...")
    
    devices_dict = {} 
    
    def detection_callback(device, advertisement_data: AdvertisementData):
        # 检查是否支持心率服务
        if HRS_UUID in advertisement_data.service_uuids:
            # 去重：只保留每个地址的第一个设备
            if device.address not in devices_dict:
                devices_dict[device.address] = device
                print(f"发现心率设备: {device.name or '未知'} ({device.address})")
    
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    await asyncio.sleep(8)  # 扫描8秒
    await scanner.stop()
    
    return list(devices_dict.values())

def show_device_selection(devices: List) -> Optional:
    """显示设备选择界面"""
    if not devices:
        return None
    
    print("\n" + "="*50)
    print("目前找到心率设备：")
    for i, device in enumerate(devices, 1):
        device_name = device.name or "未知设备"
        print(f"{i}. {device_name} ({device.address})")
    
    while True:
        try:
            choice = input("\n请选择连接的设备 (输入数字): ").strip()
            choice_num = int(choice)
            if 1 <= choice_num <= len(devices):
                selected_device = devices[choice_num - 1]
                print(f"已选择: {selected_device.name or '未知'} ({selected_device.address})")
                return selected_device
            else:
                print(f"请输入 1-{len(devices)} 之间的数字")
        except ValueError:
            print("请输入有效的数字")
        except KeyboardInterrupt:
            print("\n用户取消选择")
            return None

async def connect_to_device(device):
    """连接到指定设备"""
    print(f"正在连接到设备...")
    
    try:
        client = BleakClient(device.address)
        await client.connect()
        print(f"连接成功")
        return client
    except Exception as e:
        print(f"连接失败: {e}")
        return None

async def handle_heart_rate_notifications(client: BleakClient, monitor: HeartRateMonitor):
    """处理心率通知"""
    print("正在订阅心率数据...")
    
    def notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
        """心率数据通知处理函数"""
        try:
            parsed_data = monitor.parse_heart_rate_data(data)
            if "error" not in parsed_data:
                monitor.save_heart_rate_data(parsed_data)
                
                # 简化输出格式
                time_str = datetime.now().strftime("%H:%M:%S")
                hr = parsed_data['heart_rate']
                print(f"{time_str} 心率: {hr} BPM")
                
        except Exception as e:
            print(f"处理心率数据时出错: {e}")
    
    try:
        # 获取服务 - 修复API问题
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
        
        # 订阅通知
        await client.start_notify(heart_rate_characteristic, notification_handler)
        print("开始接收心率数据... (按 Ctrl+C 停止)")
        
        # 保持连接
        while client.is_connected:
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"处理心率通知时出错: {e}")

async def main():
    """主函数"""
    monitor = HeartRateMonitor()
    
    print("小米手环心率监控器")
    print("="*50)
    
    try:
        # 扫描设备
        devices = await scan_for_heart_rate_devices()
        
        if not devices:
            print("未找到支持心率服务的设备")
            return
        
        # 显示设备选择界面
        selected_device = show_device_selection(devices)
        if not selected_device:
            return
        
        # 连接设备
        client = await connect_to_device(selected_device)
        if not client:
            return
        
        monitor.client = client
        monitor.device = selected_device
        monitor.is_connected = True
        
        # 初始化CSV文件
        monitor.init_csv_file()
        
        # 处理心率通知
        await handle_heart_rate_notifications(client, monitor)
        
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")
    finally:
        # 清理资源
        if monitor.client and monitor.client.is_connected:
            await monitor.client.disconnect()
            print("设备已断开连接")
        
        # 关闭CSV文件
        monitor.close_csv_file()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"程序运行出错: {e}")
        print("请确保已安装必要的依赖: pip install bleak") 