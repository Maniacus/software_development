import uvicorn as uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import date, datetime
import requests
from bs4 import BeautifulSoup
import sqlite3
import threading

app = FastAPI()

# Инициализация БД
def init_database():
    with sqlite3.connect('rss.db') as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            link TEXT UNIQUE,
            source TEXT,
            published TEXT                     
        )
        ''')
        conn.commit()
init_database()

# Функция проверки RSS-ленты
def check_rss(url: str, keywords: list[str]):
    response = requests.get(url)
    response.encoding = 'utf-8'

    connection = sqlite3.connect('rss.db')
    cursor = connection.cursor()

    cursor.execute('select title from news')
    titles_list = [row[0] for row in cursor.fetchall()]
    #print('Всего заголовков в БД', len(titles_list))

    if response.status_code == 200:
        rss_feed = response.text
        soup = BeautifulSoup(rss_feed, features="xml")
        entries = soup.find_all('item')

    # запись в БД
        for item in entries:
            title = item.find('title').text
            description = item.find('description').text
            link = item.find('link').text
            published = item.find('pubDate').text
            for kw in keywords:
                if kw.lower() in title.lower() or kw.lower() in description.lower():
                    # Если новости с таким заголовком еще нет - пишем в БД
                    if title not in titles_list:
                        cursor.execute('INSERT INTO news (title, description, link, source, published) VALUES (?, ?, ?, ?, ?)', (title, description, link, url, published))
                        #print(title)
                        titles_list.append(title)
        connection.commit()
        connection.close()  


# Периодическая проверка наличия новых новостей
def periodic_rss_check():
    print('запуск фоновой проверки', datetime.now())
    with sqlite3.connect('rss.db') as conn:
        cursor = conn.cursor()
        
        # все RSS-источники
        cursor.execute('SELECT url FROM sources')
        sources = [row[0] for row in cursor.fetchall()]
        
        # все ключевые слова
        cursor.execute('SELECT word FROM keywords')
        keywords = [row[0] for row in cursor.fetchall()]
        #print(sources, keywords)
   
    if sources and keywords:
        for source in sources:
            try:
                check_rss(source, keywords)
            except Exception as e:
                print(f"Ошибка фоновой проверки {source}: {e}")
    
    # Таймер для следующего выполнения (1800 сек = 30 мин)
    threading.Timer(600, periodic_rss_check).start()

@app.on_event("startup")
def startup_event():
    # Запуск периодической проверки в отдельном потоке
    thread = threading.Thread(target=periodic_rss_check, daemon=True)
    thread.start()


# Получение информации из БД (для основной страницы)
def get_database_data():
    with sqlite3.connect('rss.db') as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT url FROM sources')
        sources = [row[0] for row in cursor.fetchall()]
        
        cursor.execute('SELECT word FROM keywords')
        keywords = [row[0] for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT title, description, link, source, published
            FROM news 
            ORDER BY published DESC
            LIMIT 30
        ''')
        # Ограничиваем 30 записями
        news = [{
            "title": row[0],
            "description": row[1],
            "link": row[2],
            "source": row[3],
            "published": row[4]
        } for row in cursor.fetchall()]
        
        return sources, keywords, news

# Эндпоинты
# Form декларация того, что параметр должен быть получен из данных формы
# (...) = параметр обязательный, аналог required=True

@app.post("/add_source")
def add_source(url: str = Form(...)):
    with sqlite3.connect('rss.db') as conn:
        try:
            conn.execute('INSERT INTO sources (url) VALUES (?)', (url,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
    return RedirectResponse(url="/", status_code=303)

@app.post("/add_keyword")
def add_keyword(word: str = Form(...)):
    with sqlite3.connect('rss.db') as conn:
        try:
            conn.execute('INSERT INTO keywords (word) VALUES (?)', (word,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete_source")
def delete_source(url: str = Form(...)):
    with sqlite3.connect('rss.db') as conn:
        conn.execute('DELETE FROM sources WHERE url = ?', (url,))
        conn.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete_keyword")
def delete_keyword(word: str = Form(...)):
    with sqlite3.connect('rss.db') as conn:
        conn.execute('DELETE FROM keywords WHERE word = ?', (word,))
        conn.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/", response_class=HTMLResponse)
def read_root():
    sources, keywords, news = get_database_data()
    
    sources_html = "\n".join(
        f'<li>{source}'
        f'<form action="/delete_source" method="post" style="display:inline">'
        f'<input type="hidden" name="url" value="{source}">'
        f'<input type="submit" value="Удалить">'
        f'</form>'
        f'</li>'
        for source in sources
    )
    
    keywords_html = "\n".join(
        f'<li>{keyword} '
        f'<form action="/delete_keyword" method="post" style="display:inline">'
        f'<input type="hidden" name="word" value="{keyword}">'
        f'<input type="submit" value="Удалить">'
        f'</form>'
        f'</li>'
        for keyword in keywords
    )
    
    news_html = "\n".join(
        f'<div style="margin-bottom:20px; border:2px solid #ccc; padding:15px">'
        f'<h3>{item["title"]}</h3>'
        f'<p>{item["description"] or "Нет описания"}</p>'
        f'<a href="{item["link"]}" target="_blank">Читать статю</a>'
        f'<hr>'
        f'<div style="color:#666; margin-top:5px">'
        f'Опубликовано: {item["published"]}'
        f'<div style="color:#666; margin-top:5px">'
        f'RSS Источник: {item["source"]}' 
        f'</div>'
        f'</div>'
        f'</div>'
        for item in news
    )

    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>RSS ленты</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #333; }}
            form {{ margin-bottom: 20px; }}
            input[type="text"] {{ padding: 5px; width: 300px; }}
            input[type="submit"] {{ padding: 5px 15px; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ margin-bottom: 5px; }}
        </style>
    </head>
    <body>
        <h2>Добавить источник</h2>
        <form action="/add_source" method="post">
            <div>
                <label>URL RSS: </label>
                <input type="text" name="url" required>
                <input type="submit" value="Добавить">
            </div>
        </form>
        
        <h2>Добавить ключевое слово</h2>
        <form action="/add_keyword" method="post">
            <div>
                <label>Ключевое слово: </label>
                <input type="text" name="word" required>
                <input type="submit" value="Добавить">
            </div>    
        </form>
        
        <h2>Текущие источники</h2>
        <ul>{sources_html}</ul>
        
        <h2>Ключевые слова</h2>
        <ul>{keywords_html}</ul>
        
        <h2>Последние новости</h2>
        <div>{news_html}</div>
    </body>
    </html>
    """

if __name__ == '__main__':
    uvicorn.run(app,
                host='127.0.0.1',
                port=8080)