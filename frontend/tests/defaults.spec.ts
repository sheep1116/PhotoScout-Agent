import {test, expect} from '@playwright/test';

test.use({timezoneId:'Asia/Shanghai'});

test('local half-hour defaults cross midnight without automatic research',async({page})=>{
  await page.clock.install({time:new Date('2026-09-11T15:40:00Z')});
  await page.addInitScript(()=>{navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail?.({code:1,message:'denied'} as GeolocationPositionError);});
  await page.route('**/v1/location/ip',route=>route.fulfill({json:{city:'南京市',note:'IP 城市，请核对'}}));
  let searches=0;
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/photo-research'))searches++;});
  await page.goto('/');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('南京市');
  await expect(page.getByLabel('拍摄日期',{exact:true})).toHaveValue('2026-09-12');
  await expect(page.getByLabel('开始时间',{exact:true})).toHaveValue('00:00');
  await expect(page.getByLabel('结束时间',{exact:true})).toHaveValue('02:30');
  await expect(page.getByLabel('结束日期',{exact:true})).toHaveValue('2026-09-12');
  await expect(page.getByText('手机主摄',{exact:true})).toHaveCount(0);
  expect(searches).toBe(0);
});

test('late location never overwrites a manually entered destination',async({page})=>{
  await page.addInitScript(()=>{navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail?.({code:1,message:'denied'} as GeolocationPositionError);});
  let release:()=>void=()=>{};
  const ready=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/v1/location/ip',async route=>{await ready;await route.fulfill({json:{city:'南京市',note:'IP 城市'}});});
  await page.goto('/');
  await page.getByLabel('目的地',{exact:true}).fill('苏州博物馆');
  release();
  await expect(page.getByRole('status')).toContainText('使用你填写的目的地');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('苏州博物馆');
});

test('browser location takes priority and keeps a next-day end date',async({page,context})=>{
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({latitude:32.06,longitude:118.79});
  await page.clock.install({time:new Date('2026-09-11T14:10:00Z')});
  let fallback=0;
  await page.route('**/v1/location/ip',route=>{fallback++;return route.fulfill({json:{city:'无锡市',note:'IP'}});});
  await page.route('**/v1/location/reverse',route=>route.fulfill({json:{city:'南京市',note:'浏览器定位'}}));
  await page.goto('/');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('南京市');
  await expect(page.getByLabel('开始时间',{exact:true})).toHaveValue('22:30');
  await expect(page.getByLabel('结束时间',{exact:true})).toHaveValue('01:00');
  await expect(page.getByLabel('拍摄日期',{exact:true})).toHaveValue('2026-09-11');
  await expect(page.getByLabel('结束日期',{exact:true})).toHaveValue('2026-09-12');
  expect(fallback).toBe(0);
});
