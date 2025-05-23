# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/ble.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x15proto/cloud/ble.proto\x12\x0bproto.cloud\"\xd8\x05\n\x08\x42tAppMsg\x12>\n\x10get_product_info\x18\x01 \x01(\x0b\x32$.proto.cloud.BtAppMsg.GetProductInfo\x12\x34\n\x0bget_ap_list\x18\x02 \x01(\x0b\x32\x1f.proto.cloud.BtAppMsg.GetApList\x12\x34\n\ndistribute\x18\x03 \x01(\x0b\x32 .proto.cloud.BtAppMsg.Distribute\x12(\n\x03req\x18\x05 \x01(\x0b\x32\x1b.proto.cloud.BtAppMsg.Debug\x1a\x85\x02\n\x0eGetProductInfo\x12\x0b\n\x03get\x18\x01 \x01(\x08\x12\x1a\n\x12\x64istribute_version\x18\x02 \x01(\r\x12\x46\n\x0cremedy_field\x18\x03 \x01(\x0b\x32\x30.proto.cloud.BtAppMsg.GetProductInfo.RemedyField\x12=\n\x07\x63ountry\x18\x04 \x01(\x0b\x32,.proto.cloud.BtAppMsg.GetProductInfo.Country\x1a*\n\x0bRemedyField\x12\x1b\n\x13\x64istribute_version2\x18\x01 \x01(\r\x1a\x17\n\x07\x43ountry\x12\x0c\n\x04\x63ode\x18\x01 \x01(\t\x1a\x1c\n\tGetApList\x12\x0f\n\x07max_num\x18\x01 \x01(\r\x1a\xb6\x01\n\nDistribute\x12\x0c\n\x04ssid\x18\x01 \x01(\t\x12\x0e\n\x06passwd\x18\x02 \x01(\t\x12\r\n\x05token\x18\x03 \x01(\t\x12\x0f\n\x07user_id\x18\x04 \x01(\t\x12\x14\n\x0ctime_zone_id\x18\x05 \x01(\t\x12\x0e\n\x06\x64omain\x18\x06 \x01(\t\x12\x0e\n\x06\x61pp_id\x18\x07 \x01(\t\x12\x10\n\x08house_id\x18\x08 \x01(\t\x12\x10\n\x08\x64\x65v_name\x18\t \x01(\t\x12\x10\n\x08hub_name\x18\n \x01(\t\x1a\x17\n\x05\x44\x65\x62ug\x12\x0e\n\x06\x64_data\x18\x01 \x01(\t\"\xae\t\n\nBtRobotMsg\x12\x39\n\x0cproduct_info\x18\x01 \x01(\x0b\x32#.proto.cloud.BtRobotMsg.ProductInfo\x12/\n\x07\x61p_list\x18\x02 \x01(\x0b\x32\x1e.proto.cloud.BtRobotMsg.ApList\x12\x43\n\x11\x64istribute_result\x18\x03 \x01(\x0b\x32(.proto.cloud.BtRobotMsg.DistributeResult\x12*\n\x03\x61\x63k\x18\x05 \x01(\x0b\x32\x1d.proto.cloud.BtRobotMsg.Debug\x1a\xe8\x02\n\x0bProductInfo\x12\x37\n\x03ret\x18\x01 \x01(\x0e\x32*.proto.cloud.BtRobotMsg.ProductInfo.Result\x12\r\n\x05\x62rand\x18\x02 \x01(\t\x12\x11\n\tcode_name\x18\x03 \x01(\t\x12\r\n\x05model\x18\x04 \x01(\t\x12\x0c\n\x04name\x18\x05 \x01(\t\x12\x12\n\nalisa_name\x18\x06 \x01(\t\x12\x11\n\tcloud_pid\x18\x07 \x01(\t\x12\x0b\n\x03mac\x18\x08 \x01(\t\x12\x1a\n\x12\x64istribute_version\x18\n \x01(\r\x12\x45\n\x0cremedy_field\x18\x0b \x01(\x0b\x32/.proto.cloud.BtRobotMsg.ProductInfo.RemedyField\x1a*\n\x0bRemedyField\x12\x1b\n\x13\x64istribute_version2\x18\x01 \x01(\r\"\x1e\n\x06Result\x12\x08\n\x04\x45_OK\x10\x00\x12\n\n\x06\x45_FAIL\x10\x01\x1a\x65\n\x06\x41pList\x12\x36\n\x07\x61p_info\x18\x01 \x03(\x0b\x32%.proto.cloud.BtRobotMsg.ApList.ApInfo\x1a#\n\x06\x41pInfo\x12\x0c\n\x04ssid\x18\x01 \x01(\t\x12\x0b\n\x03\x64\x62m\x18\x02 \x01(\x05\x1a\xd7\x03\n\x10\x44istributeResult\x12=\n\x05value\x18\x01 \x01(\x0e\x32..proto.cloud.BtRobotMsg.DistributeResult.Value\x12\x0b\n\x03mac\x18\x02 \x01(\t\x12\x0b\n\x03pid\x18\x03 \x01(\t\x12\x0c\n\x04uuid\x18\x04 \x01(\t\x12\x0f\n\x07\x61uthkey\x18\x05 \x01(\t\x12\x0b\n\x03\x64\x62m\x18\x06 \x01(\x05\x12H\n\x0b\x61iot_result\x18\x07 \x01(\x0b\x32\x33.proto.cloud.BtRobotMsg.DistributeResult.AiotResult\x1ao\n\nAiotResult\x12\x19\n\x11get_mqtt_info_ret\x18\x01 \x01(\x05\x12\x1a\n\x12get_data_point_ret\x18\x02 \x01(\x05\x12\x18\n\x10\x63onnect_mqtt_ret\x18\x03 \x01(\x05\x12\x10\n\x08\x62ind_ret\x18\x04 \x01(\x05\"\x82\x01\n\x05Value\x12\x08\n\x04\x45_OK\x10\x00\x12\r\n\tE_SRV_ERR\x10\x01\x12\x12\n\x0e\x45_AP_NOT_FOUND\x10\x02\x12\x10\n\x0c\x45_PASSWD_ERR\x10\x03\x12\x0e\n\nE_DHCP_ERR\x10\x04\x12\x0c\n\x08\x45_GW_ERR\x10\x05\x12\r\n\tE_DNS_ERR\x10\x06\x12\r\n\tE_NET_ERR\x10\x07\x1a\x17\n\x05\x44\x65\x62ug\x12\x0e\n\x06\x64_data\x18\x01 \x01(\tb\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.ble_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _BTAPPMSG._serialized_start=39
  _BTAPPMSG._serialized_end=767
  _BTAPPMSG_GETPRODUCTINFO._serialized_start=266
  _BTAPPMSG_GETPRODUCTINFO._serialized_end=527
  _BTAPPMSG_GETPRODUCTINFO_REMEDYFIELD._serialized_start=460
  _BTAPPMSG_GETPRODUCTINFO_REMEDYFIELD._serialized_end=502
  _BTAPPMSG_GETPRODUCTINFO_COUNTRY._serialized_start=504
  _BTAPPMSG_GETPRODUCTINFO_COUNTRY._serialized_end=527
  _BTAPPMSG_GETAPLIST._serialized_start=529
  _BTAPPMSG_GETAPLIST._serialized_end=557
  _BTAPPMSG_DISTRIBUTE._serialized_start=560
  _BTAPPMSG_DISTRIBUTE._serialized_end=742
  _BTAPPMSG_DEBUG._serialized_start=744
  _BTAPPMSG_DEBUG._serialized_end=767
  _BTROBOTMSG._serialized_start=770
  _BTROBOTMSG._serialized_end=1968
  _BTROBOTMSG_PRODUCTINFO._serialized_start=1006
  _BTROBOTMSG_PRODUCTINFO._serialized_end=1366
  _BTROBOTMSG_PRODUCTINFO_REMEDYFIELD._serialized_start=460
  _BTROBOTMSG_PRODUCTINFO_REMEDYFIELD._serialized_end=502
  _BTROBOTMSG_PRODUCTINFO_RESULT._serialized_start=1336
  _BTROBOTMSG_PRODUCTINFO_RESULT._serialized_end=1366
  _BTROBOTMSG_APLIST._serialized_start=1368
  _BTROBOTMSG_APLIST._serialized_end=1469
  _BTROBOTMSG_APLIST_APINFO._serialized_start=1434
  _BTROBOTMSG_APLIST_APINFO._serialized_end=1469
  _BTROBOTMSG_DISTRIBUTERESULT._serialized_start=1472
  _BTROBOTMSG_DISTRIBUTERESULT._serialized_end=1943
  _BTROBOTMSG_DISTRIBUTERESULT_AIOTRESULT._serialized_start=1699
  _BTROBOTMSG_DISTRIBUTERESULT_AIOTRESULT._serialized_end=1810
  _BTROBOTMSG_DISTRIBUTERESULT_VALUE._serialized_start=1813
  _BTROBOTMSG_DISTRIBUTERESULT_VALUE._serialized_end=1943
  _BTROBOTMSG_DEBUG._serialized_start=744
  _BTROBOTMSG_DEBUG._serialized_end=767
# @@protoc_insertion_point(module_scope)
