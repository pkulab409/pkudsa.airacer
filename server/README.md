# Server部分架构说明

## app.py
程序主入口，维护后端生命周期，心跳，前端请求，静态文件请求

## ws
WebSocket 用于管理员实时同步赛程信息

## blueprints
### admin
管理员调用的相关api，全部需要鉴权

### submission
学生提交代码，需要鉴权，在截止之后不能提交

### recording
公开API，获取比赛记录信息，用于回看等功能

### team
公开API，获取当前的队伍信息等，用于公告版等

## race
### state_machine
赛事状态机

### scoring
根据比赛信息生成积分榜单

### bracket
根据参赛信息，生成具体比赛队伍安排

## config
后端配置项

## database
数据库及数据库操作封装

流程及操作api说明
管理员前端登录，输入认证密码，所有管理员操作携带认证密码，后端操作鉴权

管理员可以发起的操作
zone: 创建zone, 删除zone
Zone-scoped race control:
  POST /api/admin/zones/{zone_id}/set-session 设置当前赛程
  POST /api/admin/zones/{zone_id}/start-race 开始一场比赛
  POST /api/admin/zones/{zone_id}/stop-race 停止一场比赛
  POST /api/admin/zones/{zone_id}/finalize 结束一个赛程
  POST /api/admin/zones/{zone_id/reset 恢复成idle状态
  GET  /api/admin/zones/{zone_id}/standings 
  GET  /api/admin/zones/{zone_id}/bracket

Zone CRUD:
  GET    /api/admin/zones 获取大区信息
  POST   /api/admin/zones 创建大区
  DELETE /api/admin/zones/{zone_id} 删除大区
  GET    /api/admin/zones/{zone_id}/teams 获取大区中的队伍列表
