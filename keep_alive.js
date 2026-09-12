const puppeteer = require('puppeteer');

(async () => {
  console.log('启动无头浏览器...');
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const page = await browser.newPage();

  // 设置浏览器标识，伪装为真实 Chrome
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

  const targetUrl = 'https://my-stock-app-nqyn5agryfl6ggzjezvvms.streamlit.app/';
  console.log(`正在访问应用: ${targetUrl}`);

  try {
    // 改用 domcontentloaded，不再死等网络空闲，彻底解决 Timeout 超时问题
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    console.log('页面基础结构已加载完成。');

    // 等待 5 秒，让页面渲染或显示休眠提示
    await new Promise(r => setTimeout(r, 5000));

    // 检查页面中是否存在“Wake it up”唤醒按钮，如果存在则自动点击
    const buttons = await page.$$('button');
    let clicked = false;
    for (const button of buttons) {
      const text = await page.evaluate(el => el.textContent, button);
      if (text && (text.includes('Wake it up') || text.includes('Yes, wake it up'))) {
        console.log('检测到应用处于休眠状态，正在自动点击唤醒按钮...');
        await button.click();
        clicked = true;
        await new Promise(r => setTimeout(r, 10000));
        break;
      }
    }

    if (!clicked) {
      console.log('应用处于在线状态，保持连接 15 秒以维持 WebSocket 活跃...');
      await new Promise(r => setTimeout(r, 15000));
    }

    console.log('保活任务执行完毕！');
  } catch (err) {
    console.error('运行过程中出现非致命异常:', err.message);
  } finally {
    await browser.close();
  }
})();
