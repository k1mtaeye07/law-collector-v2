-- 1회성 전환 (검증서버용): tb_law_clct_fail_hst (회차별 이력) → tb_law_clct_fail (law_enfc_id 당 1행)
--   law_enfc_id 별로 최초 실패 일시(inpt_dt)는 가장 이른 값, 나머지 컬럼은 가장 최근 회차 값으로 옮긴 뒤 구 테이블 삭제
--   하나의 트랜잭션: 중간에 실패하면 전체 취소 (psql 에 -v ON_ERROR_STOP=1 필수)
BEGIN;

CREATE TABLE tb_law_clct_fail (
    law_enfc_id   varchar(20)  NOT NULL,
    clct_ymd      varchar(10)  NOT NULL,
    clct_dvs_nm   varchar(10)  NOT NULL,
    law_seq       int4         NULL,
    enfc_ymd      varchar(10)  NULL,
    law_id        varchar(20)  NULL,
    law_kor_nm    varchar      NULL,
    url_path_nm   varchar      NOT NULL,
    err_nm        varchar(100) NULL,
    err_ctxt      text         NULL,
    inpt_pgm_id   varchar(20)  NOT NULL,
    inpt_dt       timestamp    NOT NULL DEFAULT now(),
    chg_pgm_id    varchar(20)  NOT NULL,
    chg_dt        timestamp    NOT NULL DEFAULT now(),
    CONSTRAINT pk_tb_law_clct_fail PRIMARY KEY (law_enfc_id)
);

COMMENT ON TABLE  tb_law_clct_fail              IS 'TB_법령수집실패';
COMMENT ON COLUMN tb_law_clct_fail.law_enfc_id  IS '법령시행아이디';
COMMENT ON COLUMN tb_law_clct_fail.clct_ymd     IS '최종실패수집일자 (실행일, CSV 날짜폴더)';
COMMENT ON COLUMN tb_law_clct_fail.clct_dvs_nm  IS '최종실패수집구분명 (full: 전체 / incr: 증분)';
COMMENT ON COLUMN tb_law_clct_fail.law_seq      IS '법령일련번호';
COMMENT ON COLUMN tb_law_clct_fail.enfc_ymd     IS '시행일자';
COMMENT ON COLUMN tb_law_clct_fail.law_id       IS '법령아이디';
COMMENT ON COLUMN tb_law_clct_fail.law_kor_nm   IS '법령한글명';
COMMENT ON COLUMN tb_law_clct_fail.url_path_nm  IS 'URL경로명 (본문 호출 URL)';
COMMENT ON COLUMN tb_law_clct_fail.err_nm       IS '오류명 (최종 실패 시 예외 종류)';
COMMENT ON COLUMN tb_law_clct_fail.err_ctxt     IS '오류내용 (최종 실패 시)';
COMMENT ON COLUMN tb_law_clct_fail.inpt_pgm_id  IS '입력프로그램아이디';
COMMENT ON COLUMN tb_law_clct_fail.inpt_dt      IS '입력일시 (최초 실패)';
COMMENT ON COLUMN tb_law_clct_fail.chg_pgm_id   IS '변경프로그램아이디';
COMMENT ON COLUMN tb_law_clct_fail.chg_dt       IS '변경일시 (최종 실패)';

INSERT INTO tb_law_clct_fail (law_enfc_id, clct_ymd, clct_dvs_nm, law_seq, enfc_ymd, law_id, law_kor_nm,
                              url_path_nm, err_nm, err_ctxt, inpt_pgm_id, inpt_dt, chg_pgm_id, chg_dt)
SELECT DISTINCT ON (h.law_enfc_id)
       h.law_enfc_id, h.clct_ymd, h.clct_dvs_nm, h.law_seq, h.enfc_ymd, h.law_id, h.law_kor_nm,
       h.url_path_nm, h.err_nm, h.err_ctxt,
       h.inpt_pgm_id, min(h.inpt_dt) OVER (PARTITION BY h.law_enfc_id),
       h.chg_pgm_id, h.chg_dt
FROM tb_law_clct_fail_hst h
WHERE COALESCE(h.law_enfc_id, '') <> ''
ORDER BY h.law_enfc_id, h.clct_ymd DESC, h.clct_fail_sn DESC;

SELECT law_enfc_id, law_kor_nm, err_nm, clct_ymd AS last_fail_ymd, inpt_dt AS first_fail_dt
FROM tb_law_clct_fail ORDER BY 1;

DROP TABLE tb_law_clct_fail_hst;

COMMIT;
