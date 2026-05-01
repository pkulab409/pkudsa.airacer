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

