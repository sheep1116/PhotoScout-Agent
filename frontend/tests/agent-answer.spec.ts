import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';

test('keeps Agent answer and links beside the mapped enhancement',async({page})=>{
  const plan=JSON.parse(readFileSync(resolve(process.cwd(),'../docs/verification/discovery-agent-plan.json'),'utf8'));
  const source=plan.sources.find((item:{url:string|null})=>item.url) || plan.sources[0];
  const spot=plan.spots[0];
  plan.agent_answer={summaries:['从公开城墙区域寻找鸡鸣寺与紫峰大厦同框，并结合现场调整焦段。'],source_ids:[source.id],candidates:[{
    id:'agent-demo',name:'城墙候选机位',camera_poi:'解放门',place_name:'南京城墙',camera_instruction:'沿公开区域寻找无遮挡位置',
    subjects:['鸡鸣寺','紫峰大厦'],shooting_direction:'朝两座建筑方向取景',composition:'使用长焦压缩空间关系',recommended_time:'蓝调时刻',
    time_judgment:'用户时段覆盖蓝调时刻，但仍需按当天天气核验。',equipment_advice:'现有长焦可作为起点。',
    settings_advice:{focal_length:'100–200mm',aperture:'f/8 起步'},source_ids:[source.id],confidence:'medium',verification_status:'mapped',
    verification_note:'已匹配高德地点；精确站位与遮挡待现场确认。',mapped_spot_id:spot.id
  }]};
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:null,note:'测试'}}));
  await page.route(/\/v1\/plans(?:\/.*)?$/,route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname.endsWith(`/plans/${plan.id}`))return route.fulfill({json:plan});
    return route.fulfill({json:[{id:plan.id,destination:plan.brief.destination,date:plan.brief.travel_date,categories:plan.brief.intent.categories,version:plan.version}]});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'我的发现',exact:true}).click();
  await expect(page.locator('.history-row')).toHaveCount(1);
  await page.locator('.history-row').click();
  await expect(page.locator('.agent-answer')).toContainText('鸡鸣寺与紫峰大厦同框');
  await expect(page.locator('.agent-candidate')).toContainText('地图与来源已关联');
  await expect(page.locator('.agent-candidate a')).toHaveAttribute('href',source.url);
  await page.locator('.agent-candidate button').click();
  await expect(page.locator('.map-edit-row')).toContainText(spot.name);
});
