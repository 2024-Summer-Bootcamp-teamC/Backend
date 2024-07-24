#chat/consumers.py
import json, logging, requests, base64, bs4, asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from openai import OpenAI
from django.conf import settings
from django_redis import get_redis_connection
from langchain import hub
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.vectorstores import FAISS
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain.chat_models import ChatOpenAI
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from concurrent.futures import ThreadPoolExecutor
from functools import partial

logger = logging.getLogger(__name__)

# 파일 핸들러 추가
file_handler = logging.FileHandler('application.log')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

client = OpenAI(api_key=settings.OPENAI_API_KEY)
redis_conn = get_redis_connection("default")

class ChatConsumer(AsyncWebsocketConsumer):
    # 각 모델의 초기 인사, 파인튜닝이 되지 않은 경우 "아직 개발중인 모델입니다." 메시지 설정
    initial_message_map = {
        '1': "반갑소, 이순신이라 하오. 무엇이 궁금하시오?",
        '2': "아직 개발 진행 중인 모델입니다.",
        '3': "아직 개발 진행 중인 모델입니다.",
        '4': "아직 개발 진행 중인 모델입니다.",
        '5': "아직 개발 진행 중인 모델입니다.",
        '6': "아직 개발 진행 중인 모델입니다.",
        '7': "아직 개발 진행 중인 모델입니다.",
        '8': "아직 개발 진행 중인 모델입니다.",
    }

    # url 가져오기
    url1_map = {
        '1': 'https://ko.wikipedia.org/wiki/이순신',  # 이순신 위키피디아
        # 추후 고도화 작업 시 추가.
        # '2': 'https://ko.wikipedia.org/wiki/세종대왕'),
        # '3': 'https://ko.wikipedia.org/wiki/장영실'),
        # '4': 'https://ko.wikipedia.org/wiki/유관순'),
        # '5': 'https://ko.wikipedia.org/wiki/스티브잡스'),
        # '6': 'https://ko.wikipedia.org/wiki/나폴레옹'),
        # '7': 'https://ko.wikipedia.org/wiki/반고흐'),
        # '8': 'https://ko.wikipedia.org/wiki/아인슈타인'),
    }

    url2_map = {
        '1': 'https://ko.wikipedia.org/wiki/거북선',  # 이순신 거북선 위키피디아

    }

    url3_map = {
        '1': 'https://ko.wikipedia.org/wiki/학익진',  # 이순신 학익진 위키피디아
    }

    url4_map = {
        '1': 'https://ko.wikipedia.org/wiki/한산도_대첩',  # 이순신 한산도 대첩 위키피디아
    }

    url5_map = {
        '1': 'https://ko.wikipedia.org/wiki/명량_해전',  # 이순신 명량 해전 위키피디아
    }

    url6_map = {
        '1': 'https://ko.wikipedia.org/wiki/노량_해전',  # 이순신 노량 해전 위키피디아
    }

    # 특정 키워드가 포함되었을 때만 RAG 검색
    search_keywords_map = {
        '1': ['이순신', '거북선', '학익진', '한산도대첩', '명량해전', '노량해전'],
    }
    # 비동기식으로 Websocket 연결 되었을 때 로직
    async def connect(self):
        self.story_id = self.scope['url_route']['kwargs']['story_id']
        self.room_group_name = f'chat_{self.story_id}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

        logger.info(f'WebSocket connected: Story ID {self.story_id}')

        # Redis 캐시 초기화
        cache_key = f'gptchat_{self.story_id}'
        redis_conn.delete(cache_key)
        logger.info(f'Redis cache reset for Story ID {self.story_id}')

        # 초기 인사 메시지 설정
        if self.story_id in self.initial_message_map:
            initial_message = self.initial_message_map[self.story_id]

            # 클라이언트에게 초기 인사 메시지 전송
            await self.send(text_data=json.dumps({
                'message': initial_message
            }))

        # 벡터 스토어 생성 작업 비동기 실행
        await self.initialize_vectorstore()

    # 벡터 스토어 초기화 함수
    # 속도 증진을 위해 웹소켓 연결이 되었을 때 벡터스토어 생성까지 해둔다.
    async def initialize_vectorstore(self):
        try:
            self.story_id = self.scope['url_route']['kwargs']['story_id']
            self.vectorstores = {}

            # url에 따른 문서 로드 및 벡터스토어 생성 함수
            async def create_vectorstore_for_url(url, key):
                loader = WebBaseLoader(
                    web_paths=[url],
                    bs_kwargs=dict(
                        parse_only=bs4.SoupStrainer(
                            "div",
                            attrs={"class": ["mw-content-ltr mw-parser-output"], "lang": ["ko"], "dir": ["ltr"]}
                        )
                    )
                )
                # 단계 1: 문서 로드(Load Documents)
                docs = loader.load()
                logger.info('문서 로드가 완료되었습니다.')

                # 단계 2: 문서 분할(Split Documents)
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=5000, chunk_overlap=50)
                splits = text_splitter.split_documents(docs)
                logger.info('문서 분할이 완료되었습니다.')

                # 단계 3: 임베딩 & 벡터스토어 생성(Create Vectorstore)
                embeddings = FastEmbedEmbeddings()
                vectorstore = FAISS.from_documents(documents=splits, embedding=embeddings)
                return key, vectorstore

            # 단계별 URL 로드 및 벡터스토어 생성
            urls = {
                '1': self.url1_map[self.story_id],
                '2': self.url2_map.get(self.story_id, ''),
                '3': self.url3_map.get(self.story_id, ''),
                '4': self.url4_map.get(self.story_id, ''),
                '5': self.url5_map.get(self.story_id, ''),
                '6': self.url6_map.get(self.story_id, ''),
            }

            tasks = [asyncio.create_task(create_vectorstore_for_url(url, key)) for key, url in urls.items() if url]
            results = await asyncio.gather(*tasks)
            self.vectorstores = dict(results)
            logger.info('벡터스토어가 성공적으로 생성되었습니다.')

        except Exception as e:
            logger.error(f"벡터스토어 초기화 중 오류 발생: {str(e)}")

    # 비동기식으로 Websocket 연결 종료할 때 로직
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        logger.info(f'WebSocket disconnected: Story ID {self.story_id}')

    #사용자가 JSON 형식으로 메시지를 보내면 호출
    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            user_message = text_data_json.get('message', '')

            if user_message:
                logger.info(f'Received message from user (Story ID {self.story_id}): {user_message}')

                gpt_response = await self.get_gpt_response(user_message)
                await self.send(text_data=json.dumps({
                    'message': gpt_response
                }))
        except json.JSONDecodeError:
            logger.error("Invalid JSON format received from client.")
            return

    #stt 처리 로직
    async def stt_process(self, speech_data):
        try:
            # Base64 디코딩
            audio_data = base64.b64decode(speech_data)

            # STT 처리를 위한 API 호출 (여기서는 네이버 STT API 예시)
            # 네이버 STT API 연동 코드
            client_id = settings.NAVER_CLIENT_ID
            client_secret = settings.NAVER_CLIENT_SECRET
            stt_url = 'https://naveropenapi.apigw.ntruss.com/recog/v1/stt'

            headers = {
                'Content-Type': 'application/octet-stream',
                'X-NCP-APIGW-API-KEY-ID': client_id,
                'X-NCP-APIGW-API-KEY': client_secret,
            }

            response = requests.post(stt_url, headers=headers, data=audio_data)
            if response.status_code == 200:
                stt_text = response.json()['text']
                return stt_text
            else:
                logger.error(f"STT API request failed with status code: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error during STT processing: {str(e)}")
            return None

    async def get_gpt_response(self, user_message):
        logger.info(f'Generating GPT response for user message (Story ID {self.story_id}): {user_message}')
        # redis를 통해 캐시에 대화 내용을 저장하기 위한 로직
        cache_key = f'gptchat_{self.story_id}'
        chat_history = redis_conn.lrange(cache_key, 0, -1)

        if not chat_history:
            chat_history = []

        # 대화 기록을 구조화하여 메시지 리스트로 변환
        messages_history = []
        for item in chat_history:
            message = json.loads(item)
            messages_history.append({"role": message["role"], "content": message["content"]})

        # 사용자 메시지 추가
        messages_history.append({"role": "user", "content": user_message})
        # 첫 인사 메시지 추가
        messages_history.append({"role": "system", "content": self.initial_message_map[self.story_id]})

        try:
            #story_id에 따른 모델을 선정하는 로직
            model_map = {
                '1': "ft:gpt-3.5-turbo-1106:personal::9nQeXXmm",
            }
            # 파인튜닝 인식을 위한 인퍼런스
            studying_content_map = {
                '1': "너는 이제부터 이순신이야. 이순신 챗봇이 아닌 이순신 역할을 맡아 나랑 대화를 진행할거야. 조선시대 장군의 말투를 사용하며, 해요체는 사용해서는 안되고, 하오체를 사용해야 해."
            }

            if self.story_id in model_map:
                model = model_map[self.story_id]
                studying_content = studying_content_map[self.story_id]
                search_keywords = self.search_keywords_map[self.story_id]

                # "role"이 "user"일 때의 가장 최근 1개의 "content" 추출
                user_messages_history = [msg["content"] for msg in messages_history if msg["role"] == "user"][-1:]

                # "role"이 "assistant"일 때의 가장 최근 1개의 "content" 추출
                assistant_messages_history = [msg["content"] for msg in messages_history if msg["role"] == "assistant"][-1:]

                # 특정 키워드가 포함된 경우에만 RAG 검색 실행
                keywords = search_keywords
                if any(keyword in user_message for keyword in keywords):
                    # 특정 키워드에 따라 벡터스토어를 선택하는 로직
                    def select_vectorstore(user_message):
                        vectorstores = []
                        if "이순신" in user_message:
                            vectorstores.append(self.vectorstores.get('1'))
                        if "거북선" in user_message:
                            vectorstores.append(self.vectorstores.get('2'))
                        if "학익진" in user_message:
                            vectorstores.append(self.vectorstores.get('3'))
                        if "한산도대첩" in user_message:
                            vectorstores.append(self.vectorstores.get('4'))
                        if "명량해전" in user_message:
                            vectorstores.append(self.vectorstores.get('5'))
                        if "노량해전" in user_message:
                            vectorstores.append(self.vectorstores.get('6'))
                        return vectorstores

                    # RAG 검색에 사용될 벡터스토어 선택
                    selected_vectorstores = select_vectorstore(user_message)

                    if selected_vectorstores:
                        # 여러 벡터스토어를 합쳐서 검색할 수 있도록 처리
                        all_retrieved_docs = []
                        for vectorstore in selected_vectorstores:
                            retriever = vectorstore.as_retriever(search_kwargs=dict(k=1))
                            retrieved_docs = retriever.get_relevant_documents(user_message)
                            all_retrieved_docs.extend(retrieved_docs)

                        # 중복된 문서 제거 (필요한 경우)
                        unique_retrieved_docs = list({doc.page_content: doc for doc in all_retrieved_docs}.values())
                        logger.info(f"검색된 문서: {unique_retrieved_docs}")

                        # 단계 5: 프롬프트 생성(Create Prompt)
                        prompt = hub.pull("rlm/rag-prompt")
                        logger.info('프롬프트 생성이 완료되었습니다.')

                        def format_docs(docs):
                            # 검색한 문서 결과를 하나의 문단으로 합쳐줍니다.
                            return "\n\n".join(doc.page_content for doc in docs)

                        logger.info('문서 합병이 완료되었습니다.')

                        # 단계 6: LLM 모델 생성 (기존 모델 불러오기)
                        llm = ChatOpenAI(openai_api_key=settings.OPENAI_API_KEY)
                        logger.info('LLM 모델 생성이 완료되었습니다.')

                        # 단계 7: 체인 생성(Create Chain)
                        rag_chain = (
                                {"context": retriever | format_docs, "question": RunnablePassthrough()}
                                | prompt
                                | llm
                                | StrOutputParser()
                        )
                        logger.info('체인 생성이 완료되었습니다.')

                        # 단계 8: 비동기로 체인 실행(Run Chain)
                        rag_response = await asyncio.to_thread(rag_chain.invoke, user_message)
                        logger.info('체인 실행이 완료되었습니다.')
                    else:
                        rag_response = None
                else:
                    rag_response = None

                # 메시지 리스트 구성
                messages = [
                    # 파인튜닝된 정보 인퍼런스
                    {"role": "system", "content": f"{studying_content}"},
                    {"role": "user", "content": user_message},
                    # 추출한 과거 메시지를 학습하는 과정
                    {"role": "system", "content": f"나의 최근 질문 내용이야.: '{user_messages_history}'"},
                    {"role": "system", "content": f"너의 최근 답변 내용이야. 이 답변에 이어서 대답을 해줘.: '{assistant_messages_history}'"},
                    # RAG에서 얻어온 정보
                    {"role": "system", "content": f"인물에 대한 자세한 정보야.: '{rag_response}'"},
                    # 유의사항 추가
                    {"role": "system", "content": "대화 맥락에 맞지 않는 단어나 이해할 수 없는 단어는 말하지 않도록 해. 또한, 어려운 단어 사용은 지양해."},
                    {"role": "system", "content": "너는 내 질문에 관련한 대답만 해야 하며, 관련 없는 대답은 하지 않도록 해."},
                    {"role": "system", "content": "넌 나의 성별을 몰라. 너 임의로 내 성별을 지정하지 마."},
                    {"role": "system", "content": "괄호 사용 금지. 한자랑 영어 사용 금지. 기술적 용어 사용 금지. 했던 말 반복 금지."},
                    {"role": "system", "content": "너에게 주어진 역할에 대해 최선을 다하며, 1인칭 시점으로 얘기를 해. 넌 챗봇이 아닌 인물 그 자체가 되는거야."},
                    {"role": "system", "content": "어떠한 내용의 답변이라도 너에게 주어진 성격과 말투를 일관되게 유지시켜야 해."},
                ]

                response = client.chat.completions.create(
                    model=model,
                    messages=messages
                )

                if response and response.choices and len(response.choices) > 0:
                    gpt_response = response.choices[0].message.content
                    messages_history.append({"role": "assistant", "content": gpt_response})
                    redis_conn.ltrim(cache_key, -6, -1)  # 최근 6개의 대화만 유지
                    redis_conn.rpush(cache_key, json.dumps({"role": "user", "content": user_message}))
                    redis_conn.rpush(cache_key, json.dumps({"role": "assistant", "content": gpt_response}))
                else:
                    gpt_response = "답변 생성이 불가능 합니다."

            #story_id를 할당하지 못했을 때 빈 객체 값으로 반환
            else:
                gpt_response = f"아직 개발이 완료되지 않은 모델 story_id:{self.story_id}입니다."
                return gpt_response

        except KeyError as ke:
            logger.error(f"OpenAI API 응답 처리 중 KeyError: {str(ke)}가 발생했습니다.")
            gpt_response = "GPT가 예상하지 못한 응답 형식입니다."

        except Exception as e:
            logger.error(f"OpenAI API를 호출하는 중 Error: {str(e)}가 발생했습니다")
            gpt_response = f"GPT에서 응답 생성 중 오류가 발생했습니다: {str(e)}"

        return gpt_response
