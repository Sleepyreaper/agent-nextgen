-- Database schema for AI-powered application evaluation system (PostgreSQL)

-- Table: Applications - Stores all uploaded applications
CREATE TABLE IF NOT EXISTS Applications (
    ApplicationID SERIAL PRIMARY KEY,
    ApplicantName VARCHAR(255) NOT NULL,
    Email VARCHAR(255),
    PhoneNumber VARCHAR(50),
    Position VARCHAR(255),
    UploadedDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ApplicationText TEXT,
    OriginalFileName VARCHAR(500),
    FileType VARCHAR(50),
    BlobStoragePath VARCHAR(1000),
    IsTrainingExample BOOLEAN DEFAULT FALSE,
    WasSelected BOOLEAN,
    Status VARCHAR(50) DEFAULT 'Pending',
    CreatedBy VARCHAR(255),
    UpdatedDate TIMESTAMP,
    Notes TEXT
);

-- Table: Grades - Stores academic or performance grades
CREATE TABLE IF NOT EXISTS Grades (
    GradeID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    GradeType VARCHAR(100),
    GradeValue VARCHAR(50),
    MaxValue VARCHAR(50),
    Subject VARCHAR(255),
    Date TIMESTAMP,
    Notes TEXT
);

-- Table: AIEvaluations - Stores AI agent evaluations
CREATE TABLE IF NOT EXISTS AIEvaluations (
    EvaluationID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    AgentName VARCHAR(255),
    EvaluationDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    OverallScore NUMERIC(5,2),
    TechnicalSkillsScore NUMERIC(5,2),
    CommunicationScore NUMERIC(5,2),
    ExperienceScore NUMERIC(5,2),
    CulturalFitScore NUMERIC(5,2),
    Strengths TEXT,
    Weaknesses TEXT,
    Recommendation VARCHAR(50),
    DetailedAnalysis TEXT,
    ComparisonToExcellence TEXT,
    ModelUsed VARCHAR(255),
    ProcessingTimeMs INTEGER
);

-- Table: SelectionDecisions - Final human decisions
CREATE TABLE IF NOT EXISTS SelectionDecisions (
    DecisionID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    DecisionDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Decision VARCHAR(50),
    DecisionBy VARCHAR(255),
    Justification TEXT,
    AgreedWithAI BOOLEAN
);

-- Table: TrainingFeedback - Track how AI improves
CREATE TABLE IF NOT EXISTS TrainingFeedback (
    FeedbackID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    EvaluationID INTEGER REFERENCES AIEvaluations(EvaluationID),
    FeedbackDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FeedbackType VARCHAR(100),
    HumanScore NUMERIC(5,2),
    FeedbackNotes TEXT,
    ProvidedBy VARCHAR(255)
);

-- Table: Schools - High school information
CREATE TABLE IF NOT EXISTS Schools (
    SchoolID SERIAL PRIMARY KEY,
    SchoolName VARCHAR(500) NOT NULL,
    City VARCHAR(255),
    State VARCHAR(50),
    ZipCode VARCHAR(10),
    County VARCHAR(255),
    SchoolType VARCHAR(100),
    GradeKind VARCHAR(100),
    LongDescription TEXT,
    DataSource VARCHAR(255),
    LastUpdated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Latitude DOUBLE PRECISION,
    Longitude DOUBLE PRECISION
);

-- Table: SchoolSocioeconomicData - SES and demographic info
CREATE TABLE IF NOT EXISTS SchoolSocioeconomicData (
    SESDataID SERIAL PRIMARY KEY,
    SchoolID INTEGER REFERENCES Schools(SchoolID),
    MedianHouseholdIncome NUMERIC(12,2),
    MedianIncome VARCHAR(100),
    FreeLunchPercentage NUMERIC(5,2),
    PovertyLevel VARCHAR(100),
    AvgParentalEducation VARCHAR(100),
    UrbanRural VARCHAR(50),
    DataYear INTEGER,
    ReliabilityRating VARCHAR(50)
);

-- Table: SchoolPrograms - Advanced learning programs offered
CREATE TABLE IF NOT EXISTS SchoolPrograms (
    ProgramID SERIAL PRIMARY KEY,
    SchoolID INTEGER REFERENCES Schools(SchoolID),
    ProgramName VARCHAR(255) NOT NULL,
    ProgramType VARCHAR(100),
    Description TEXT,
    NumberOfCourses INTEGER,
    EnrolledStudents INTEGER,
    SelectionCriteria TEXT,
    StartYear INTEGER,
    EstimatedDifficulty INTEGER,
    DataYear INTEGER
);

-- Table: StudentSchoolContext - Links students to schools and program access
CREATE TABLE IF NOT EXISTS StudentSchoolContext (
    ContextID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    SchoolID INTEGER REFERENCES Schools(SchoolID),
    SchoolName VARCHAR(500),
    IdentificationConfidence NUMERIC(5,2),
    AnalysisDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ProgramAccessScore NUMERIC(5,2),
    ProgramParticipationScore NUMERIC(5,2),
    RelativeAdvantageScore NUMERIC(5,2),
    NumberOfAdvancedPrograms INTEGER,
    NumberOfProgramsAccessed INTEGER,
    APCoursesAvailable INTEGER,
    APCoursesTaken INTEGER,
    IBCoursesAvailable INTEGER,
    IBCoursesTaken INTEGER,
    HonorsCoursesTaken INTEGER,
    STEMProgramsAvailable INTEGER,
    STEMProgramsAccessed INTEGER,
    GiftedProgram BOOLEAN,
    SchoolSESLevel VARCHAR(100),
    MedianHouseholdIncome NUMERIC(12,2),
    FreeLunchPct NUMERIC(5,2),
    PercentageOfPeersUsingPrograms NUMERIC(5,2),
    ComparisonNotes TEXT,
    AccessibilityRating VARCHAR(100)
);

-- Table: AgentAuditLogs - Auditable agent write trail
CREATE TABLE IF NOT EXISTS AgentAuditLogs (
    AuditID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    AgentName VARCHAR(255) NOT NULL,
    SourceFileName VARCHAR(500),
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: TianaApplications - Parsed application profiles
CREATE TABLE IF NOT EXISTS TianaApplications (
    TianaApplicationID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    AgentName VARCHAR(255) NOT NULL,
    EssaySummary TEXT,
    RecommendationTexts TEXT,
    ReadinessScore NUMERIC(5,2),
    Confidence VARCHAR(50),
    ParsedJson TEXT,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: MulanRecommendations - Parsed recommendation letters
CREATE TABLE IF NOT EXISTS MulanRecommendations (
    MulanRecommendationID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    AgentName VARCHAR(255) NOT NULL,
    RecommenderName VARCHAR(255),
    RecommenderRole VARCHAR(255),
    EndorsementStrength NUMERIC(5,2),
    SpecificityScore NUMERIC(5,2),
    Summary TEXT,
    RawText TEXT,
    ParsedJson TEXT,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: MerlinEvaluations - Final student recommendations
CREATE TABLE IF NOT EXISTS MerlinEvaluations (
    MerlinEvaluationID SERIAL PRIMARY KEY,
    ApplicationID INTEGER REFERENCES Applications(ApplicationID),
    AgentName VARCHAR(255) NOT NULL,
    OverallScore NUMERIC(5,2),
    Recommendation VARCHAR(100),
    Rationale TEXT,
    Confidence VARCHAR(50),
    ParsedJson TEXT,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for better performance
CREATE INDEX IF NOT EXISTS IX_Applications_Status ON Applications(Status);
CREATE INDEX IF NOT EXISTS IX_Applications_IsTrainingExample ON Applications(IsTrainingExample);
CREATE INDEX IF NOT EXISTS IX_Applications_UploadedDate ON Applications(UploadedDate);
CREATE INDEX IF NOT EXISTS IX_AIEvaluations_ApplicationID ON AIEvaluations(ApplicationID);
CREATE INDEX IF NOT EXISTS IX_AIEvaluations_Recommendation ON AIEvaluations(Recommendation);
CREATE INDEX IF NOT EXISTS IX_SelectionDecisions_ApplicationID ON SelectionDecisions(ApplicationID);
CREATE INDEX IF NOT EXISTS IX_Schools_SchoolName ON Schools(SchoolName);
CREATE INDEX IF NOT EXISTS IX_StudentSchoolContext_ApplicationID ON StudentSchoolContext(ApplicationID);
CREATE INDEX IF NOT EXISTS IX_StudentSchoolContext_SchoolID ON StudentSchoolContext(SchoolID);
CREATE INDEX IF NOT EXISTS IX_AgentAuditLogs_ApplicationID ON AgentAuditLogs(ApplicationID);
CREATE INDEX IF NOT EXISTS IX_TianaApplications_ApplicationID ON TianaApplications(ApplicationID);
CREATE INDEX IF NOT EXISTS IX_MulanRecommendations_ApplicationID ON MulanRecommendations(ApplicationID);
CREATE INDEX IF NOT EXISTS IX_MerlinEvaluations_ApplicationID ON MerlinEvaluations(ApplicationID);
