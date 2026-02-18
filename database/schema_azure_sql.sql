-- Database schema for AI-powered application evaluation system (Azure SQL Database)
-- Compatible with Azure SQL Database and SQL Server 2019+

-- Table: Applications - Stores all uploaded applications
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Applications]') AND type in (N'U'))
BEGIN
    CREATE TABLE Applications (
        ApplicationID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicantName NVARCHAR(255) NOT NULL,
        Email NVARCHAR(255),
        PhoneNumber NVARCHAR(50),
        Position NVARCHAR(255),
        UploadedDate DATETIME2 DEFAULT GETDATE(),
        ApplicationText NVARCHAR(MAX),
        OriginalFileName NVARCHAR(500),
        FileType NVARCHAR(50),
        BlobStoragePath NVARCHAR(1000),
        IsTrainingExample BIT DEFAULT 0,
        WasSelected BIT,
        Status NVARCHAR(50) DEFAULT 'Pending',
        CreatedBy NVARCHAR(255),
        UpdatedDate DATETIME2,
        Notes NVARCHAR(MAX),
        TranscriptText NVARCHAR(MAX),
        RecommendationText NVARCHAR(MAX)
    );
END
GO

-- Table: Grades - Stores academic or performance grades
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Grades]') AND type in (N'U'))
BEGIN
    CREATE TABLE Grades (
        GradeID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        GradeType NVARCHAR(100),
        GradeValue NVARCHAR(50),
        MaxValue NVARCHAR(50),
        Subject NVARCHAR(255),
        Date DATETIME2,
        Notes NVARCHAR(MAX)
    );
END
GO

-- Table: AIEvaluations - Stores AI agent evaluations
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[AIEvaluations]') AND type in (N'U'))
BEGIN
    CREATE TABLE AIEvaluations (
        EvaluationID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        AgentName NVARCHAR(255),
        EvaluationDate DATETIME2 DEFAULT GETDATE(),
        OverallScore DECIMAL(5,2),
        TechnicalSkillsScore DECIMAL(5,2),
        CommunicationScore DECIMAL(5,2),
        ExperienceScore DECIMAL(5,2),
        CulturalFitScore DECIMAL(5,2),
        Strengths NVARCHAR(MAX),
        Weaknesses NVARCHAR(MAX),
        Recommendation NVARCHAR(50),
        DetailedAnalysis NVARCHAR(MAX),
        ComparisonToExcellence NVARCHAR(MAX),
        ModelUsed NVARCHAR(255),
        ProcessingTimeMs INT
    );
END
GO

-- Table: SelectionDecisions - Final human decisions
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[SelectionDecisions]') AND type in (N'U'))
BEGIN
    CREATE TABLE SelectionDecisions (
        DecisionID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        DecisionDate DATETIME2 DEFAULT GETDATE(),
        Decision NVARCHAR(50),
        DecisionBy NVARCHAR(255),
        Justification NVARCHAR(MAX),
        AgreedWithAI BIT
    );
END
GO

-- Table: TrainingFeedback - Track how AI improves
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[TrainingFeedback]') AND type in (N'U'))
BEGIN
    CREATE TABLE TrainingFeedback (
        FeedbackID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        EvaluationID INT REFERENCES AIEvaluations(EvaluationID),
        FeedbackDate DATETIME2 DEFAULT GETDATE(),
        FeedbackType NVARCHAR(100),
        HumanScore DECIMAL(5,2),
        FeedbackNotes NVARCHAR(MAX),
        ProvidedBy NVARCHAR(255)
    );
END
GO

-- Table: UserFeedback - Store dashboard feedback submissions
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[UserFeedback]') AND type in (N'U'))
BEGIN
    CREATE TABLE UserFeedback (
        FeedbackID INT IDENTITY(1,1) PRIMARY KEY,
        FeedbackDate DATETIME2 DEFAULT GETDATE(),
        FeedbackType NVARCHAR(50) NOT NULL,
        Message NVARCHAR(MAX) NOT NULL,
        Email NVARCHAR(255),
        Page NVARCHAR(1000),
        AppVersion NVARCHAR(50),
        UserAgent NVARCHAR(MAX),
        TriageJSON NVARCHAR(MAX),
        IssueURL NVARCHAR(1000),
        Status NVARCHAR(50) DEFAULT 'received'
    )
END
GO

-- Table: Schools - High school information
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Schools]') AND type in (N'U'))
BEGIN
    CREATE TABLE Schools (
        SchoolID INT IDENTITY(1,1) PRIMARY KEY,
        SchoolName NVARCHAR(500) NOT NULL,
        City NVARCHAR(255),
        State NVARCHAR(50),
        ZipCode NVARCHAR(10),
        County NVARCHAR(255),
        SchoolType NVARCHAR(100),
        GradeKind NVARCHAR(100),
        LongDescription NVARCHAR(MAX),
        DataSource NVARCHAR(255),
        LastUpdated DATETIME2 DEFAULT GETDATE(),
        Latitude FLOAT,
        Longitude FLOAT
    );
END
GO

-- Table: SchoolSocioeconomicData - SES and demographic info
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[SchoolSocioeconomicData]') AND type in (N'U'))
BEGIN
    CREATE TABLE SchoolSocioeconomicData (
        SESDataID INT IDENTITY(1,1) PRIMARY KEY,
        SchoolID INT REFERENCES Schools(SchoolID),
        MedianHouseholdIncome DECIMAL(12,2),
        MedianIncome NVARCHAR(100),
        FreeLunchPercentage DECIMAL(5,2),
        PovertyLevel NVARCHAR(100),
        AvgParentalEducation NVARCHAR(100),
        UrbanRural NVARCHAR(50),
        DataYear INT,
        ReliabilityRating NVARCHAR(50)
    );
END
GO

-- Table: SchoolPrograms - Advanced learning programs offered
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[SchoolPrograms]') AND type in (N'U'))
BEGIN
    CREATE TABLE SchoolPrograms (
        ProgramID INT IDENTITY(1,1) PRIMARY KEY,
        SchoolID INT REFERENCES Schools(SchoolID),
        ProgramName NVARCHAR(255) NOT NULL,
        ProgramType NVARCHAR(100),
        Description NVARCHAR(MAX),
        NumberOfCourses INT,
        EnrolledStudents INT,
        SelectionCriteria NVARCHAR(MAX),
        StartYear INT,
        EstimatedDifficulty INT,
        DataYear INT
    );
END
GO

-- Table: StudentSchoolContext - Links students to schools and program access
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[StudentSchoolContext]') AND type in (N'U'))
BEGIN
    CREATE TABLE StudentSchoolContext (
        ContextID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        SchoolID INT REFERENCES Schools(SchoolID),
        SchoolName NVARCHAR(500),
        IdentificationConfidence DECIMAL(5,2),
        AnalysisDate DATETIME2 DEFAULT GETDATE(),
        ProgramAccessScore DECIMAL(5,2),
        ProgramParticipationScore DECIMAL(5,2),
        RelativeAdvantageScore DECIMAL(5,2),
        NumberOfAdvancedPrograms INT,
        NumberOfProgramsAccessed INT,
        APCoursesAvailable INT,
        APCoursesTaken INT,
        IBCoursesAvailable INT,
        IBCoursesTaken INT,
        HonorsCoursesTaken INT,
        STEMProgramsAvailable INT,
        STEMProgramsAccessed INT,
        GiftedProgram BIT,
        SchoolSESLevel NVARCHAR(100),
        MedianHouseholdIncome DECIMAL(12,2),
        FreeLunchPct DECIMAL(5,2),
        PercentageOfPeersUsingPrograms DECIMAL(5,2),
        ComparisonNotes NVARCHAR(MAX),
        AccessibilityRating NVARCHAR(100)
    );
END
GO

-- Table: AgentAuditLogs - Auditable agent write trail
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[AgentAuditLogs]') AND type in (N'U'))
BEGIN
    CREATE TABLE AgentAuditLogs (
        AuditID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        AgentName NVARCHAR(255) NOT NULL,
        SourceFileName NVARCHAR(500),
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
END
GO

-- Table: TianaApplications - Parsed application profiles
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[TianaApplications]') AND type in (N'U'))
BEGIN
    CREATE TABLE TianaApplications (
        TianaApplicationID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        AgentName NVARCHAR(255) NOT NULL,
        EssaySummary NVARCHAR(MAX),
        RecommendationTexts NVARCHAR(MAX),
        ReadinessScore DECIMAL(5,2),
        Confidence NVARCHAR(50),
        ParsedJson NVARCHAR(MAX),
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
END
GO

-- Table: MulanRecommendations - Parsed recommendation letters
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[MulanRecommendations]') AND type in (N'U'))
BEGIN
    CREATE TABLE MulanRecommendations (
        MulanRecommendationID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        AgentName NVARCHAR(255) NOT NULL,
        RecommenderName NVARCHAR(255),
        RecommenderRole NVARCHAR(255),
        EndorsementStrength DECIMAL(5,2),
        SpecificityScore DECIMAL(5,2),
        Summary NVARCHAR(MAX),
        RawText NVARCHAR(MAX),
        ParsedJson NVARCHAR(MAX),
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
END
GO

-- Table: MerlinEvaluations - Final student recommendations
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[MerlinEvaluations]') AND type in (N'U'))
BEGIN
    CREATE TABLE MerlinEvaluations (
        MerlinEvaluationID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        AgentName NVARCHAR(255) NOT NULL,
        OverallScore DECIMAL(5,2),
        Recommendation NVARCHAR(100),
        Rationale NVARCHAR(MAX),
        Confidence NVARCHAR(50),
        ParsedJson NVARCHAR(MAX),
        CreatedAt DATETIME2 DEFAULT GETDATE()
    );
END
GO

-- Table: AuroraEvaluations - Formatted final presentation of evaluations
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[AuroraEvaluations]') AND type in (N'U'))
BEGIN
    CREATE TABLE AuroraEvaluations (
        AuroraEvaluationID INT IDENTITY(1,1) PRIMARY KEY,
        ApplicationID INT REFERENCES Applications(ApplicationID),
        AgentName NVARCHAR(255) NOT NULL DEFAULT 'Aurora',
        FormattedEvaluation NVARCHAR(MAX) NOT NULL,
        MerlinScore DECIMAL(5,2),
        MerlinRecommendation NVARCHAR(100),
        AgentsCompleted NVARCHAR(MAX),
        CreatedAt DATETIME2 DEFAULT GETDATE(),
        UpdatedAt DATETIME2 DEFAULT GETDATE()
    );
END
GO

-- Table: TestSubmissions - Track test runs for persistence
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[TestSubmissions]') AND type in (N'U'))
BEGIN
    CREATE TABLE TestSubmissions (
        TestSubmissionID INT IDENTITY(1,1) PRIMARY KEY,
        SessionID NVARCHAR(255) UNIQUE NOT NULL,
        StudentCount INT,
        ApplicationIDs NVARCHAR(MAX),
        Status NVARCHAR(50) DEFAULT 'in_progress',
        CreatedAt DATETIME2 DEFAULT GETDATE(),
        UpdatedAt DATETIME2 DEFAULT GETDATE()
    );
END
GO

-- Indexes for better performance
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Applications_Status' AND object_id = OBJECT_ID('Applications'))
    CREATE INDEX IX_Applications_Status ON Applications(Status);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Applications_IsTrainingExample' AND object_id = OBJECT_ID('Applications'))
    CREATE INDEX IX_Applications_IsTrainingExample ON Applications(IsTrainingExample);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Applications_UploadedDate' AND object_id = OBJECT_ID('Applications'))
    CREATE INDEX IX_Applications_UploadedDate ON Applications(UploadedDate);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_AIEvaluations_ApplicationID' AND object_id = OBJECT_ID('AIEvaluations'))
    CREATE INDEX IX_AIEvaluations_ApplicationID ON AIEvaluations(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_AIEvaluations_Recommendation' AND object_id = OBJECT_ID('AIEvaluations'))
    CREATE INDEX IX_AIEvaluations_Recommendation ON AIEvaluations(Recommendation);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_SelectionDecisions_ApplicationID' AND object_id = OBJECT_ID('SelectionDecisions'))
    CREATE INDEX IX_SelectionDecisions_ApplicationID ON SelectionDecisions(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Schools_SchoolName' AND object_id = OBJECT_ID('Schools'))
    CREATE INDEX IX_Schools_SchoolName ON Schools(SchoolName);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_StudentSchoolContext_ApplicationID' AND object_id = OBJECT_ID('StudentSchoolContext'))
    CREATE INDEX IX_StudentSchoolContext_ApplicationID ON StudentSchoolContext(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_StudentSchoolContext_SchoolID' AND object_id = OBJECT_ID('StudentSchoolContext'))
    CREATE INDEX IX_StudentSchoolContext_SchoolID ON StudentSchoolContext(SchoolID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_AgentAuditLogs_ApplicationID' AND object_id = OBJECT_ID('AgentAuditLogs'))
    CREATE INDEX IX_AgentAuditLogs_ApplicationID ON AgentAuditLogs(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_TianaApplications_ApplicationID' AND object_id = OBJECT_ID('TianaApplications'))
    CREATE INDEX IX_TianaApplications_ApplicationID ON TianaApplications(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_MulanRecommendations_ApplicationID' AND object_id = OBJECT_ID('MulanRecommendations'))
    CREATE INDEX IX_MulanRecommendations_ApplicationID ON MulanRecommendations(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_MerlinEvaluations_ApplicationID' AND object_id = OBJECT_ID('MerlinEvaluations'))
    CREATE INDEX IX_MerlinEvaluations_ApplicationID ON MerlinEvaluations(ApplicationID);
GO

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_AuroraEvaluations_ApplicationID' AND object_id = OBJECT_ID('AuroraEvaluations'))
    CREATE INDEX IX_AuroraEvaluations_ApplicationID ON AuroraEvaluations(ApplicationID);
GO
