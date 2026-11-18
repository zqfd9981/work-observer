"""真实 BOSS 详情 JSON 到业务字段的只读转换；不负责认证或发送请求。"""

from work_observer.connectors.mcp_probe import ProbeError


def normalize_boss_detail(raw: dict, expected_job_id: str, access_context: dict) -> dict:
    if raw.get("code") != 0 or not isinstance(raw.get("zpData"), dict):
        raise ProbeError("SOURCE_ERROR")
    data = raw["zpData"]
    info = data.get("jobInfo")
    if not isinstance(info, dict):
        raise ProbeError("MALFORMED_DETAIL")
    if info.get("encryptId") != expected_job_id:
        raise ProbeError("DETAIL_ID_MISMATCH")
    description = data.get("jobDetail") or info.get("postDescription")
    if not isinstance(description, str) or not description.strip():
        raise ProbeError("MISSING_DETAIL_DESCRIPTION")
    company = data.get("brandComInfo") or {}
    record = {
        "job_id": expected_job_id,
        "description": description,
        **{
            key: access_context[key]
            for key in ("security_id", "lid", "job_url")
            if access_context.get(key)
        },
    }
    fields = {
        "jobName": "title",
        "salaryDesc": "salary",
        "experienceName": "experience",
        "degreeName": "education",
        "address": "address",
        "positionName": "source_position_name",
        "daysPerWeekDesc": "days_per_week",
        "leastMonthDesc": "least_month",
        "payTypeDesc": "pay_type",
        "recruitmentCountDesc": "recruitment_count",
    }
    for source, target in fields.items():
        value = info.get(source)
        if isinstance(value, str) and value:
            record[target] = value
    for source, target in {
        "brandName": "company",
        "encryptBrandId": "source_company_id",
        "industryName": "industry",
        "scaleName": "scale",
        "stageName": "stage",
        "introduce": "company_introduction",
    }.items():
        value = company.get(source)
        if isinstance(value, str) and value:
            record[target] = value
    city = info.get("cityName") or info.get("locationName")
    if isinstance(city, str) and city:
        record["city"] = city
    if info.get("position") is not None:
        record["source_position_code"] = str(info["position"])
    if type(info.get("jobType")) is int:
        raw_type = info["jobType"]
        record["raw_job_type"] = raw_type
        if raw_type == 4:  # 安装连接器已核实的实习类型；其他编码不猜测。
            record["employment_type"] = "实习"
    skills = info.get("showSkills") or info.get("skills")
    if isinstance(skills, list) and all(isinstance(item, str) for item in skills):
        record["skills"] = skills
    record["source_status_raw"] = {
        key: info[key] for key in ("jobStatusDesc", "invalidStatus") if key in info
    }
    return record
