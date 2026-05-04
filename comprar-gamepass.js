const puppeteer = require('puppeteer');

async function buyGamepass(gamepassId, robuxAmount, cookie) {
    console.log(`[NODE] Iniciando compra da gamepass ${gamepassId}...`);

    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
    });

    try {
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');

        // Injetar cookie
        await page.setCookie({
            name: '.ROBLOSECURITY',
            value: cookie,
            domain: '.roblox.com',
            path: '/'
        });

        // Acessa a gamepass
        const gamepassUrl = `https://www.roblox.com/game-pass/${gamepassId}`;
        console.log(`[NODE] Acessando: ${gamepassUrl}`);
        await page.goto(gamepassUrl, { waitUntil: 'networkidle2', timeout: 30000 });

        await new Promise(resolve => setTimeout(resolve, 3000));

        // Verifica se ja possui
        const content = await page.content();
        if (content.includes('You already own') || content.includes('Purchased')) {
            console.log('[NODE] SUCESSO: Gamepass ja possuida!');
            return { success: true, message: 'Gamepass ja possuida!' };
        }

        // Primeiro clique no Buy
        console.log('[NODE] Clicando no botão Buy (1ª vez)...');
        try {
            const clicked = await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button, a[role="button"]'));
                const btn = buttons.find(b => b.textContent.trim() === 'Buy' || b.textContent.includes('Comprar'));
                if (btn) { btn.click(); return true; }
                return false;
            });
            if (!clicked) throw new Error('Botão não encontrado');
            console.log('[NODE] Botão Buy clicado (1ª vez)!');
        } catch (e) {
            try {
                await page.click('#purchase-button');
                console.log('[NODE] Botão purchase-button clicado (1ª vez)!');
            } catch (e2) {
                console.log('[NODE] Nenhum botão de compra encontrado');
                await page.screenshot({ path: 'debug-gamepass.png' });
                return { success: false, message: 'Botão de compra nao encontrado' };
            }
        }

        // Aguarda a modal abrir completamente
        console.log('[NODE] Aguardando modal de compra abrir...');
        await new Promise(resolve => setTimeout(resolve, 5000));

        // Tira screenshot para debug
        await page.screenshot({ path: 'debug-modal.png' });
        console.log('[NODE] Screenshot da modal: debug-modal.png');

        // Segundo clique no Buy DENTRO da modal - usando page.click
        console.log('[NODE] Tentando clicar no Buy da modal (2ª vez)...');

        // Estratégia: usa page.$eval com seletor específico
        const modalBuyClicked = await page.evaluate(() => {
            // Procura pelo botão Buy dentro de qualquer container modal
            const modalSelectors = [
                '[role="dialog"]',
                '.modal',
                '.ReactModal__Content',
                '[class*="modal"]',
                '[class*="Modal"]'
            ];

            let targetButton = null;

            // Procura em modais
            for (const selector of modalSelectors) {
                const modals = document.querySelectorAll(selector);
                for (const modal of modals) {
                    const rect = modal.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;

                    const buttons = modal.querySelectorAll('button, a[role="button"]');
                    for (const btn of buttons) {
                        const text = btn.textContent.trim();
                        if (text === 'Buy' || text.includes('Comprar')) {
                            targetButton = btn;
                            break;
                        }
                    }
                    if (targetButton) break;
                }
                if (targetButton) break;
            }

            // Se não achou em modais, procura na página toda
            if (!targetButton) {
                const allButtons = Array.from(document.querySelectorAll('button, a[role="button"]'));
                const visibleButtons = allButtons.filter(btn => {
                    const rect = btn.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                });
                targetButton = visibleButtons.find(b => b.textContent.trim() === 'Buy' || b.textContent.includes('Comprar'));
            }

            if (targetButton) {
                // Tenta múltiplas vezes com eventos adequados
                targetButton.scrollIntoView({ block: 'center' });
                targetButton.focus();

                // Dispara eventos de mouse
                ['mousedown', 'mouseup', 'click'].forEach(eventType => {
                    targetButton.dispatchEvent(new MouseEvent(eventType, {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    }));
                });

                // Click nativo
                targetButton.click();

                return true;
            }

            return false;
        });

        if (modalBuyClicked) {
            console.log('[NODE] Botão Buy clicado na modal (2ª vez)!');
        } else {
            console.log('[NODE] ERRO: Não conseguiu encontrar/clicar no Buy da modal');
            await page.screenshot({ path: 'debug-gamepass.png' });
            return { success: false, message: 'Nao conseguiu clicar no botão da modal' };
        }

        // Aguarda processamento da compra
        await new Promise(resolve => setTimeout(resolve, 4000));

        // Verifica resultado
        const pageText = await page.evaluate(() => document.body.innerText);

        if (pageText.includes('You already own') ||
            pageText.includes('Purchased') ||
            pageText.includes('success') ||
            pageText.includes('comprado') ||
            pageText.includes('owned')) {
            console.log('[NODE] SUCESSO: Gamepass comprada!');
            return { success: true, message: 'Gamepass comprada com sucesso!' };
        }

        // Verifica se o botão de compra sumiu
        const buyButtonStillExists = await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll('button, a[role="button"]'));
            return buttons.some(btn => btn.textContent.trim() === 'Buy' || btn.textContent.includes('Comprar'));
        });

        if (!buyButtonStillExists) {
            console.log('[NODE] SUCESSO: Botão de compra sumiu, provavelmente comprado!');
            return { success: true, message: 'Gamepass provavelmente comprada!' };
        }

        // Debug
        await page.screenshot({ path: 'debug-gamepass.png' });
        console.log('[NODE] Screenshot salvo: debug-gamepass.png');

        return { success: false, message: 'Nao foi possivel confirmar a compra' };

    } catch (error) {
        console.error('[NODE] Erro:', error.message);
        return { success: false, message: `Erro: ${error.message}` };
    } finally {
        await browser.close();
    }
}

// Execução principal
(async () => {
    const gamepassId = process.argv[2];
    const robuxAmount = process.argv[3] || '0';
    const cookie = process.env.ROBLOX_COOKIE || '';

    if (!gamepassId) {
        console.error('Uso: node comprar-gamepass.js <gamepass_id> [robux_amount]');
        process.exit(1);
    }

    if (!cookie) {
        console.error('ERRO: ROBLOX_COOKIE nao configurado no .env');
        process.exit(1);
    }

    const result = await buyGamepass(gamepassId, robuxAmount, cookie);
    console.log('[NODE] Resultado:', JSON.stringify(result));
    process.exit(result.success ? 0 : 1);
})();
